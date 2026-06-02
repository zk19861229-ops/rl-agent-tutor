"""Load source configuration from the active workspace."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import workspace_path
from .models import SourceConfig
from .registry import SourceRegistry


DEFAULT_SOURCES: tuple[SourceConfig, ...] = (
    SourceConfig(id="arxiv", type="arxiv", name="arXiv", priority="core"),
    SourceConfig(id="github", type="github", name="GitHub", priority="normal"),
    SourceConfig(id="youtube", type="youtube", name="YouTube", priority="supplemental"),
    SourceConfig(id="website", type="website", name="Web Articles", priority="normal"),
    SourceConfig(
        id="local-library",
        type="local_directory",
        name="Local Library",
        priority="core",
        config={"path": "library/manual"},
    ),
)


def source_config_path() -> Path:
    return workspace_path("config", "sources.yaml")


def load_source_registry() -> SourceRegistry:
    data = _load_config_data(source_config_path())
    enabled = set(_get_nested(data, ("defaults", "enabled"), []))
    disabled = set(_get_nested(data, ("defaults", "disabled"), []))

    sources: list[SourceConfig] = []
    for source in DEFAULT_SOURCES:
        enabled_by_default = source.enabled
        if enabled:
            enabled_by_default = source.id in enabled or source.type in enabled
        if source.id in disabled or source.type in disabled:
            enabled_by_default = False
        sources.append(source.model_copy(update={"enabled": enabled_by_default}))

    for item in data.get("custom_sources", []) or []:
        if not isinstance(item, dict):
            continue
        source = _source_from_mapping(item)
        if source is not None:
            sources.append(source)

    return SourceRegistry(sources)


def save_source_registry(sources: list[SourceConfig]) -> Path:
    """Persist the current source list as workspace config.

    The file intentionally uses the documented simple YAML shape so it remains
    hand-editable and does not require PyYAML at runtime.
    """
    path = source_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["defaults:", "  enabled:"]
    default_ids = {source.id for source in DEFAULT_SOURCES}
    for source in sources:
        if source.id in default_ids and source.enabled:
            lines.append(f"    - {source.id}")
    disabled = [source.id for source in sources if source.id in default_ids and not source.enabled]
    if disabled:
        lines.append("  disabled:")
        for source_id in disabled:
            lines.append(f"    - {source_id}")

    custom = [source for source in sources if source.id not in default_ids]
    lines.append("custom_sources:")
    if not custom:
        lines.append("  []")
    for source in custom:
        lines.extend(_dump_source(source))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _dump_source(source: SourceConfig) -> list[str]:
    lines = [
        f"  - id: {_yaml_scalar(source.id)}",
        f"    type: {_yaml_scalar(source.type)}",
        f"    name: {_yaml_scalar(source.name)}",
        f"    enabled: {'true' if source.enabled else 'false'}",
        f"    priority: {_yaml_scalar(source.priority)}",
    ]
    for key, value in source.config.items():
        if value is None or value == "":
            continue
        lines.append(f"    {key}: {_yaml_scalar(str(value))}")
    return lines


def _yaml_scalar(value: str) -> str:
    if not value:
        return '""'
    if any(ch in value for ch in ":#[]{}&,*?|-<>=!%@\\\"'") or value.strip() != value:
        return json.dumps(value, ensure_ascii=False)
    return value


def _source_from_mapping(item: dict[str, Any]) -> SourceConfig | None:
    source_id = str(item.get("id") or "").strip()
    source_type = str(item.get("type") or "").strip()
    name = str(item.get("name") or source_id).strip()
    if not source_id or not source_type:
        return None
    known = {"id", "type", "name", "enabled", "priority", "config"}
    config = dict(item.get("config") or {})
    for key, value in item.items():
        if key not in known:
            config[key] = value
    try:
        return SourceConfig(
            id=source_id,
            type=source_type,
            name=name,
            enabled=bool(item.get("enabled", True)),
            priority=_normalize_priority(str(item.get("priority") or "normal")),
            config=config,
        )
    except Exception:
        return None


def _normalize_priority(value: str) -> str:
    return {
        "high": "core",
        "medium": "normal",
        "low": "supplemental",
    }.get(value.strip().lower(), value.strip().lower() or "normal")


def _load_config_data(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}

    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except ImportError:
        pass
    except Exception:
        return {}

    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return _parse_simple_yaml(text)


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    """Small parser for the documented sources.yaml shape.

    It supports:
    - defaults.enabled / defaults.disabled as dash lists
    - custom_sources as a list of flat mappings
    This avoids making PyYAML a hard runtime dependency.
    """
    data: dict[str, Any] = {"defaults": {}, "custom_sources": []}
    section = ""
    defaults_key = ""
    current: dict[str, Any] | None = None

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if not raw_line.startswith(" ") and stripped.endswith(":"):
            section = stripped[:-1]
            defaults_key = ""
            current = None
            continue
        if section == "defaults":
            if stripped.endswith(":"):
                defaults_key = stripped[:-1]
                data["defaults"].setdefault(defaults_key, [])
            elif stripped.startswith("- ") and defaults_key:
                data["defaults"].setdefault(defaults_key, []).append(_scalar(stripped[2:]))
        elif section == "custom_sources":
            if stripped.startswith("- "):
                if current:
                    data["custom_sources"].append(current)
                current = {}
                rest = stripped[2:].strip()
                if rest:
                    key, value = _split_pair(rest)
                    current[key] = _scalar(value)
            elif current is not None and ":" in stripped:
                key, value = _split_pair(stripped)
                current[key] = _scalar(value)
    if current:
        data["custom_sources"].append(current)
    return data


def _split_pair(text: str) -> tuple[str, str]:
    key, _, value = text.partition(":")
    return key.strip(), value.strip()


def _scalar(value: str) -> Any:
    value = value.strip().strip("\"'")
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    return value


def _get_nested(data: dict[str, Any], path: tuple[str, ...], default: Any) -> Any:
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return default if cur is None else cur
