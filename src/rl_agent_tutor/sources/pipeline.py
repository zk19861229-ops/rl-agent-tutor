"""Source provider orchestration and persistence."""
from __future__ import annotations

from pathlib import Path

from ..config import workspace_path
from ..models import LearningNode, Resource
from ..store import append_resource
from .health import record_source_fetch
from .providers import providers_for_registry
from .registry import SourceRegistry


def source_dirs() -> dict[str, Path]:
    dirs = {
        "workspace": workspace_path(),
        "papers": workspace_path("library", "papers"),
        "code": workspace_path("library", "code"),
        "blogs": workspace_path("library", "notes", "blogs"),
        "transcripts": workspace_path("library", "notes", "transcripts"),
    }
    for key in ("papers", "code", "blogs", "transcripts"):
        dirs[key].mkdir(parents=True, exist_ok=True)
    return dirs


def run_source_providers(
    node: LearningNode,
    registry: SourceRegistry,
    plan_json: dict,
) -> list[Resource]:
    dirs = source_dirs()
    out: list[Resource] = []
    for provider in providers_for_registry(registry):
        result = provider.fetch(node, plan_json, dirs)
        record_source_fetch(result)
        for resource in result.resources:
            append_resource(resource)
            out.append(resource)
    return out
