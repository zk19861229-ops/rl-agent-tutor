"""Persistent source health records."""
from __future__ import annotations

import json
from datetime import datetime

from ..config import ensure_workspace, workspace_path
from ..storage import get_text_storage
from .models import SourceFetchResult, SourceHealth


def source_health_path():
    return workspace_path("progress", "source_health.json")


def load_source_health() -> dict[str, SourceHealth]:
    path = source_health_path()
    key = _key()
    storage = get_text_storage()
    if not storage.exists(key):
        return {}
    try:
        data = json.loads(storage.read_text(key))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, SourceHealth] = {}
    for source_id, item in data.items():
        try:
            out[source_id] = SourceHealth.model_validate(item)
        except Exception:
            continue
    return out


def save_source_health(records: dict[str, SourceHealth]) -> None:
    ensure_workspace()
    text = json.dumps(
        {source_id: record.model_dump() for source_id, record in records.items()},
        ensure_ascii=False,
        indent=2,
    )
    get_text_storage().write_text(_key(), text + "\n")


def record_source_fetch(result: SourceFetchResult) -> SourceHealth:
    records = load_source_health()
    health = SourceHealth(
        source_id=result.source_id,
        ok=not result.error,
        last_error=result.error,
        candidate_count=len(result.candidates) or len(result.resources),
        last_fetched_at=datetime.now().isoformat(timespec="seconds"),
    )
    records[result.source_id] = health
    save_source_health(records)
    return health


def _key() -> str:
    return "progress/source_health.json"
