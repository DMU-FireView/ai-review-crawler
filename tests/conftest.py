"""
DB가 필요한 통합 테스트용 공통 fixture.

DATABASE_URL(환경변수 또는 core/settings.py 기본값)로 접속을 시도해 실패하면
해당 모듈 전체를 skip한다 — 로컬에 Postgres가 없어도 나머지 테스트는 그대로 돈다.

engine(모듈 스코프)은 스키마 생성/정리만 담당한다. asyncpg 연결은 이벤트 루프에
묶이는데, pytest-asyncio 기본값은 테스트마다 새 루프를 쓰므로 세션용 엔진은
테스트마다(session fixture, 함수 스코프) 새로 만든다.
"""

import os

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from review_crawler.core.db.base import Base, create_session_factory
from review_crawler.core.settings import get_settings

DATABASE_URL = os.environ.get("DATABASE_URL", get_settings().database_url)


@pytest.fixture(scope="module")
async def engine():
    eng = create_async_engine(DATABASE_URL)
    try:
        async with eng.connect():
            pass
    except Exception:
        await eng.dispose()
        pytest.skip("로컬 Postgres에 연결할 수 없어 통합 테스트를 건너뜁니다 (DATABASE_URL 확인).")

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await eng.dispose()

    yield None

    eng = create_async_engine(DATABASE_URL)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest.fixture
async def session(engine):
    eng = create_async_engine(DATABASE_URL)

    # 각 테스트가 이전 테스트의 commit된 row에 영향받지 않도록 매번 비운다.
    # (rollback은 이 세션 안에서 커밋 안 한 변경만 되돌리므로 그것만으로는 부족하다.)
    async with eng.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())

    factory = create_session_factory(eng)
    async with factory() as s:
        yield s
        await s.rollback()
    await eng.dispose()
