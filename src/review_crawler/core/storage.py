"""수집 결과를 JSON 파일로 저장/조회합니다.

저장 경로: {data_dir}/{platform}/{kind}_{타임스탬프}.json
"""

import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from review_crawler.core.settings import Settings, get_settings


def _base_dir(settings: Settings | None = None) -> Path:
    return (settings or get_settings()).data_dir


def save(
    platform: str,
    kind: str,
    items: list[BaseModel],
    settings: Settings | None = None,
) -> Path:
    """수집 결과를 저장하고 파일 경로를 반환합니다.

    kind: "products" | "reviews"
    """
    target_dir = _base_dir(settings) / platform
    target_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = target_dir / f"{kind}_{stamp}.json"

    payload = [item.model_dump(mode="json") for item in items]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def list_files(platform: str, settings: Settings | None = None) -> list[Path]:
    target_dir = _base_dir(settings) / platform
    if not target_dir.exists():
        return []
    return sorted(target_dir.glob("*.json"))