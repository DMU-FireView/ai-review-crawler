"""
TTL 판단 + job 생성 유스케이스.

fresh / stale / queued 세 가지 응답을 조립한다. 실제 크롤링은 worker가 담당하며
이 서비스는 job을 만들기만 하고 기다리지 않는다(비동기 하이브리드 수집 원칙).
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from review_crawler.core.db.models import CollectionJob, ProductRow, ReviewRow
from review_crawler.core.db.repository import (
    CollectionJobRepository,
    ProductRepository,
    ReviewRepository,
)
from review_crawler.core.settings import Settings, get_settings

CollectionStatus = Literal["fresh", "stale", "queued"]


@dataclass
class CollectionResult:
    status: CollectionStatus
    product: ProductRow | None
    reviews: list[ReviewRow]
    reviews_next_cursor: str | None
    job: CollectionJob | None


class CollectionService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.products = ProductRepository(session)
        self.reviews = ReviewRepository(session)
        self.jobs = CollectionJobRepository(session)

    async def get_or_queue(
        self,
        platform: str,
        product_id: str,
        review_limit: int = 20,
        review_cursor: str | None = None,
    ) -> CollectionResult:
        product = await self.products.get(platform, product_id)

        if product is not None and self._is_fresh(product.last_collected_at):
            reviews, next_cursor = await self.reviews.list_page(
                platform, product_id, limit=review_limit, cursor=review_cursor
            )
            return CollectionResult(
                status="fresh",
                product=product,
                reviews=reviews,
                reviews_next_cursor=next_cursor,
                job=None,
            )

        job, _created = await self.jobs.create_or_get_active(platform, product_id)

        if product is None:
            return CollectionResult(
                status="queued", product=None, reviews=[], reviews_next_cursor=None, job=job
            )

        reviews, next_cursor = await self.reviews.list_page(
            platform, product_id, limit=review_limit, cursor=review_cursor
        )
        return CollectionResult(
            status="stale",
            product=product,
            reviews=reviews,
            reviews_next_cursor=next_cursor,
            job=job,
        )

    def _is_fresh(self, last_collected_at: datetime) -> bool:
        ttl = timedelta(seconds=self.settings.collection_ttl_seconds)
        now = datetime.now(UTC)
        if last_collected_at.tzinfo is None:
            last_collected_at = last_collected_at.replace(tzinfo=UTC)
        return now - last_collected_at < ttl
