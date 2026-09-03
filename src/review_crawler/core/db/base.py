"""
SQLAlchemy 엔진/세션 설정.

접속 정보는 core/settings.py 의 database_url 을 사용합니다.
"""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from review_crawler.core.settings import get_settings


class Base(DeclarativeBase):
    """모든 ORM 모델의 공통 베이스."""


def create_engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
