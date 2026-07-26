"""
결과 확인용 FastAPI 앱 (얇은 껍데기).

수집 로직은 전부 collectors/ 에만 있습니다. 이 파일은 그것을 HTTP 로 노출만 합니다.
-> 본 서버 이식 시 core/ 와 collectors/ 만 가져가고 이 파일은 버리면 됩니다.
"""

from functools import lru_cache

from fastapi import FastAPI, HTTPException

from review_crawler.core.base import BaseCollector
from review_crawler.core.discovery import LoadFailure, discover
from review_crawler.core.exceptions import CollectorError, NotSupportedError

app = FastAPI(title="ai-review-crawler", version="0.1.0")


@lru_cache
def _registry() -> tuple[dict[str, type[BaseCollector]], tuple[LoadFailure, ...]]:
    registry, failures = discover()
    return registry, tuple(failures)


def _get_collector_cls(platform: str) -> type[BaseCollector]:
    registry, _ = _registry()
    cls = registry.get(platform)
    if cls is None:
        raise HTTPException(
            status_code=404,
            detail=f"'{platform}' collector 가 없습니다. 사용 가능: {sorted(registry)}",
        )
    return cls


def _to_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotSupportedError):
        return HTTPException(status_code=501, detail=str(exc))
    if isinstance(exc, CollectorError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@app.get("/platforms")
async def platforms() -> dict:
    registry, failures = _registry()
    return {
        "available": sorted(registry.keys()),
        "failed": [f.package for f in failures],
    }


@app.get("/{platform}/search")
async def search(platform: str, keyword: str, limit: int = 20):
    collector_cls = _get_collector_cls(platform)
    try:
        async with collector_cls() as collector:
            return await collector.search_products(keyword, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc) from exc


@app.get("/{platform}/products/{product_id}")
async def product(platform: str, product_id: str):
    collector_cls = _get_collector_cls(platform)
    try:
        async with collector_cls() as collector:
            return await collector.get_product(product_id)
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc) from exc


@app.get("/{platform}/products/{product_id}/reviews")
async def reviews(platform: str, product_id: str, limit: int = 50):
    collector_cls = _get_collector_cls(platform)
    try:
        async with collector_cls() as collector:
            return await collector.get_reviews(product_id, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc) from exc