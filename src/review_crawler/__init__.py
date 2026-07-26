"""
review_crawler

커머스 플랫폼 상품/리뷰 수집 패키지.

본 서버(FastAPI)에 이식할 때는 core/ 와 collectors/ 를 그대로 가져가서
아래 공개 API 만 사용하면 됩니다.

    from review_crawler import discover, NotSupportedError

    registry, _ = discover()
    async with registry["elevenst"]() as collector:
        reviews = await collector.get_reviews(product_id)
"""

from review_crawler.core.base import BaseCollector
from review_crawler.core.browser import BrowserCollector
from review_crawler.core.discovery import discover
from review_crawler.core.exceptions import (
    CollectorError,
    MissingCredentialError,
    NotSupportedError,
    ParseError,
)
from review_crawler.core.models import Product, Review

__all__ = [
    "BaseCollector",
    "BrowserCollector",
    "CollectorError",
    "MissingCredentialError",
    "NotSupportedError",
    "ParseError",
    "Product",
    "Review",
    "discover",
]