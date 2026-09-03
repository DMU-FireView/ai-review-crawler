"""
TTL 기반 하이브리드 조회 API.

specs/2026-09-03-api-contract.md 의 계약을 구현한다.
"""

from datetime import datetime
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from review_crawler.core.db.base import create_engine, create_session_factory
from review_crawler.core.db.models import CollectionJob, ProductRow, ReviewRow
from review_crawler.core.service.collection import CollectionResult, CollectionService

router = APIRouter(prefix="/api/v1")


@lru_cache
def _session_factory() -> async_sessionmaker[AsyncSession]:
    return create_session_factory(create_engine())


def _api_error(status_code: int, code: str, message: str, detail: object = None) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": code, "message": message, "detail": detail}},
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _serialize_product(row: ProductRow) -> dict:
    return {
        "platform": row.platform,
        "product_id": row.product_id,
        "name": row.name,
        "url": row.url,
        "brand": row.brand,
        "manufacturer": row.manufacturer,
        "seller": row.seller,
        "price": row.price,
        "thumbnail_url": row.thumbnail_url,
        "category": row.category,
        "review_count": row.review_count,
        "rating": float(row.rating) if row.rating is not None else None,
        "last_collected_at": _iso(row.last_collected_at),
    }


def _serialize_review(row: ReviewRow) -> dict:
    return {
        "review_id": row.review_id,
        "content": row.content,
        "rating": float(row.rating) if row.rating is not None else None,
        "author": row.author,
        "written_at": _iso(row.written_at),
        "option": row.option,
        "images": list(row.images or []),
        "helpful_count": row.helpful_count,
    }


def _serialize_job(job: CollectionJob) -> dict:
    return {
        "id": job.id,
        "platform": job.platform,
        "product_id": job.product_id,
        "status": job.status,
        "product_status": job.product_status,
        "review_status": job.review_status,
        "last_error": job.last_error,
    }


def _build_body(result: CollectionResult) -> dict:
    body: dict = {"status": result.status}
    if result.product is not None:
        body["product"] = _serialize_product(result.product)
    if result.status != "queued":
        body["reviews"] = {
            "items": [_serialize_review(r) for r in result.reviews],
            "next_cursor": result.reviews_next_cursor,
        }
    if result.job is not None:
        body["job"] = _serialize_job(result.job)
    return body


@router.get("/{platform}/products/{product_id}")
async def get_product(
    platform: str,
    product_id: str,
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
) -> JSONResponse:
    session_factory = _session_factory()
    async with session_factory() as session:
        service = CollectionService(session)
        result = await service.get_or_queue(
            platform, product_id, review_limit=limit, review_cursor=cursor
        )
        await session.commit()

    status_code = 202 if result.status == "queued" else 200
    return JSONResponse(status_code=status_code, content=_build_body(result))


@router.get("/jobs/{job_id}")
async def get_job(job_id: int) -> dict:
    session_factory = _session_factory()
    async with session_factory() as session:
        job = await session.get(CollectionJob, job_id)

    if job is None:
        raise _api_error(404, "NOT_FOUND", "job을 찾을 수 없습니다.")
    return _serialize_job(job)
