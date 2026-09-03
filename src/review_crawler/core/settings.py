"""
설정 로딩.

⚠️ 중요: import 시점에 Settings 를 만들지 않습니다.

이 패키지는 나중에 본 서버(FastAPI)에 라이브러리로 이식됩니다.
import 만으로 .env 를 강제하거나 종료해버리면 호스트 앱이 죽으므로,
실제로 값이 필요한 시점(get_settings 호출)에 lazy 로 생성합니다.

- CLI 로 쓸 때  : cli.py 가 .env 존재 여부를 검사하고 친절히 안내
- 라이브러리로 쓸 때 : OS 환경변수/호스트 설정을 그대로 사용, .env 없어도 무관
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# src/review_crawler/core/settings.py -> 프로젝트 루트
PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── 공통 ──────────────────────────────
    request_timeout: float = 15.0
    request_delay: float = 1.0
    headless: bool = True

    # PostgreSQL 접속 정보 (환경변수 DATABASE_URL 로 덮어쓸 수 있음)
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/review_crawler"

    # 상품+리뷰 묶음이 신선하다고 볼 기준 시간(초). 하나의 job이 상품/리뷰를 함께 갱신하므로
    # 우선은 둘을 분리하지 않고 하나의 값(리뷰 쪽 6h 기준)으로 둔다.
    # 상품/리뷰 TTL을 따로 둘지는 Phase 2 이후 실사용 데이터를 보고 재검토한다.
    collection_ttl_seconds: int = 6 * 60 * 60

    # ── 플랫폼별 인증 정보 ──────────────────
    # 자기 플랫폼에 키가 필요하면 여기에 추가하고,
    # .env.example 에도 반드시 빈 값으로 추가하세요.
    elevenst_api_key: str | None = None
    naver_client_id: str | None = None
    naver_client_secret: str | None = None


@lru_cache
def get_settings() -> Settings:
    """설정 싱글턴. 최초 호출 시에만 생성됩니다."""
    return Settings()


def env_file_exists() -> bool:
    """CLI 에서 .env 존재 여부를 안내하기 위한 헬퍼."""
    return ENV_FILE.exists()