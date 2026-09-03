"""
collection_jobs 를 claim 해서 collector 를 실행하는 워커.

product/review 는 서로 독립적으로 성공/실패를 기록한다 — 하나가 실패해도
다른 하나는 커밋되어야 하기 때문이다(부분 실패 정책).
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from review_crawler.core.db.repository import (
    CollectionJobRepository,
    ProductRepository,
    ReviewRepository,
)
from review_crawler.core.discovery import discover
from review_crawler.core.exceptions import CollectorError

logger = logging.getLogger(__name__)

REVIEW_COLLECT_LIMIT = 50


async def run_once(session: AsyncSession, worker_id: str) -> bool:
    """job 하나를 claim 해서 처리한다. 처리할 job이 없으면 False를 반환한다."""
    jobs = CollectionJobRepository(session)
    job = await jobs.claim_one(worker_id)
    if job is None:
        return False

    # claim 결과를 먼저 커밋해 다른 워커가 이 job을 다시 집어가지 않게 한다.
    await session.commit()

    job_id, platform, product_id = job.id, job.platform, job.product_id

    registry, _ = discover()
    collector_cls = registry.get(platform)
    if collector_cls is None:
        await jobs.mark_completed(
            job_id,
            product_status="failed",
            review_status="failed",
            error=f"'{platform}' collector가 등록되어 있지 않습니다.",
        )
        await session.commit()
        return True

    products = ProductRepository(session)
    reviews_repo = ReviewRepository(session)

    product_status = "failed"
    review_status = "failed"
    errors: list[str] = []

    try:
        async with collector_cls() as collector:
            try:
                product = await collector.get_product(product_id)
                await products.upsert(product)
                product_status = "succeeded"
            except CollectorError as exc:
                errors.append(f"product: {exc}")
                logger.warning("[%s/%s] 상품 수집 실패: %s", platform, product_id, exc)

            try:
                review_items = await collector.get_reviews(
                    product_id, limit=REVIEW_COLLECT_LIMIT
                )
                await reviews_repo.upsert_many(platform, product_id, review_items)
                review_status = "succeeded"
            except CollectorError as exc:
                errors.append(f"review: {exc}")
                logger.warning("[%s/%s] 리뷰 수집 실패: %s", platform, product_id, exc)
    except Exception as exc:  # noqa: BLE001 - 워커는 job을 FAILED로 남기고 계속 돌아야 한다
        errors.append(f"unexpected: {exc}")
        logger.exception("[%s/%s] collector 실행 중 예상치 못한 오류", platform, product_id)

    await jobs.mark_completed(
        job_id,
        product_status=product_status,
        review_status=review_status,
        error="; ".join(errors) if errors else None,
    )
    await session.commit()
    return True
