"""
products/reviews/collection_jobs 에 대한 DB 접근 계층.

Pydantic Product/Review(core/models.py) ↔ ORM row(core/db/models.py) 변환은
이 모듈이 전담한다. 상위 계층(service)은 SQLAlchemy를 직접 알 필요가 없다.
"""

import base64
import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import text

from review_crawler.core.db.models import CollectionJob, ProductRow, ReviewRow
from review_crawler.core.models import Product, Review

_REVIEW_UPDATE_COLUMNS = (
    "content",
    "rating",
    "author",
    "written_at",
    "option",
    "images",
    "helpful_count",
    "last_collected_at",
)


def _encode_review_cursor(written_at: datetime | None, review_id: str) -> str:
    payload = json.dumps([written_at.isoformat() if written_at else None, review_id])
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_review_cursor(cursor: str) -> tuple[datetime | None, str]:
    written_at_raw, review_id = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    written_at = datetime.fromisoformat(written_at_raw) if written_at_raw else None
    return written_at, review_id


class ProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, platform: str, product_id: str) -> ProductRow | None:
        return await self.session.get(ProductRow, (platform, product_id))

    async def upsert(self, product: Product) -> None:
        values = {
            "name": product.name,
            "url": product.url,
            "brand": product.brand,
            "manufacturer": product.manufacturer,
            "seller": product.seller,
            "price": product.price,
            "thumbnail_url": product.thumbnail_url,
            "category": product.category,
            "review_count": product.review_count,
            "rating": product.rating,
            "last_collected_at": datetime.now(UTC),
        }
        stmt = pg_insert(ProductRow).values(
            platform=product.platform, product_id=product.product_id, **values
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["platform", "product_id"], set_=values
        )
        await self.session.execute(stmt)


class ReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_page(
        self,
        platform: str,
        product_id: str,
        limit: int = 20,
        cursor: str | None = None,
    ) -> tuple[list[ReviewRow], str | None]:
        """written_at 내림차순 cursor 페이지네이션. limit+1개를 가져와 다음 페이지 여부를 판단."""
        stmt = select(ReviewRow).where(
            ReviewRow.platform == platform, ReviewRow.product_id == product_id
        )
        if cursor is not None:
            written_at, review_id = _decode_review_cursor(cursor)
            if written_at is not None:
                stmt = stmt.where(
                    or_(
                        ReviewRow.written_at < written_at,
                        and_(ReviewRow.written_at == written_at, ReviewRow.review_id < review_id),
                        ReviewRow.written_at.is_(None),
                    )
                )
            else:
                stmt = stmt.where(ReviewRow.written_at.is_(None), ReviewRow.review_id < review_id)

        stmt = stmt.order_by(
            ReviewRow.written_at.desc().nulls_last(), ReviewRow.review_id.desc()
        ).limit(limit + 1)

        result = await self.session.execute(stmt)
        rows = list(result.scalars())

        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = _encode_review_cursor(last.written_at, last.review_id)
        return rows, next_cursor

    async def upsert_many(self, platform: str, product_id: str, reviews: list[Review]) -> None:
        if not reviews:
            return
        now = datetime.now(UTC)
        rows = [
            {
                "platform": platform,
                "product_id": product_id,
                "review_id": review.review_id,
                "content": review.content,
                "rating": review.rating,
                "author": review.author,
                "written_at": review.written_at,
                "option": review.option,
                "images": review.images,
                "helpful_count": review.helpful_count,
                "last_collected_at": now,
            }
            for review in reviews
        ]
        stmt = pg_insert(ReviewRow).values(rows)
        update_cols = {col: getattr(stmt.excluded, col) for col in _REVIEW_UPDATE_COLUMNS}
        stmt = stmt.on_conflict_do_update(
            index_elements=["platform", "product_id", "review_id"], set_=update_cols
        )
        await self.session.execute(stmt)


class CollectionJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, job_id: int) -> CollectionJob | None:
        return await self.session.get(CollectionJob, job_id)

    async def get_active(self, platform: str, product_id: str) -> CollectionJob | None:
        stmt = select(CollectionJob).where(
            CollectionJob.platform == platform,
            CollectionJob.product_id == product_id,
            CollectionJob.status.in_(("pending", "running")),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_or_get_active(
        self, platform: str, product_id: str
    ) -> tuple[CollectionJob, bool]:
        """활성 job이 있으면 그걸 반환(created=False), 없으면 새로 만든다(created=True).

        동시 요청에도 partial unique index(uq_collection_jobs_inflight)가 중복 생성을
        막아준다 — SAVEPOINT 안에서 insert 해보고 충돌하면 기존 job을 재조회한다.
        """
        idempotency_key = hashlib.sha256(f"{platform}:{product_id}".encode()).hexdigest()[:32]
        try:
            async with self.session.begin_nested():
                job = CollectionJob(
                    platform=platform,
                    product_id=product_id,
                    idempotency_key=idempotency_key,
                )
                self.session.add(job)
                await self.session.flush()
            return job, True
        except IntegrityError:
            existing = await self.get_active(platform, product_id)
            if existing is None:
                raise
            return existing, False

    async def claim_one(self, worker_id: str, lease_seconds: int = 120) -> CollectionJob | None:
        """PENDING이거나 lease가 만료된 RUNNING job 하나를 원자적으로 가져간다."""
        stmt = text(
            """
            UPDATE collection_jobs
            SET status = 'running',
                locked_by = :worker_id,
                locked_at = now(),
                lease_expires_at = now() + make_interval(secs => :lease_seconds),
                attempt_count = attempt_count + 1
            WHERE id = (
                SELECT id FROM collection_jobs
                WHERE status = 'pending'
                   OR (status = 'running' AND lease_expires_at < now())
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id
            """
        )
        result = await self.session.execute(
            stmt, {"worker_id": worker_id, "lease_seconds": lease_seconds}
        )
        row = result.first()
        if row is None:
            return None
        # 원시 SQL UPDATE는 세션의 identity map을 갱신하지 않으므로, 이미 로드돼
        # 있던 객체가 있다면 populate_existing으로 DB 최신값을 강제로 다시 읽는다.
        return await self.session.get(CollectionJob, row.id, populate_existing=True)

    async def mark_completed(
        self,
        job_id: int,
        *,
        product_status: str,
        review_status: str,
        error: str | None = None,
    ) -> None:
        if product_status == "succeeded" and review_status == "succeeded":
            status = "succeeded"
        elif product_status == "failed" and review_status == "failed":
            status = "failed"
        else:
            status = "partial"

        job = await self.session.get(CollectionJob, job_id)
        if job is None:
            return
        job.status = status
        job.product_status = product_status
        job.review_status = review_status
        job.last_error = error
        job.completed_at = datetime.now(UTC)
