"""Configurable resource source registry."""
from .config import load_source_registry, save_source_registry, source_config_path
from .health import load_source_health, record_source_fetch, save_source_health
from .models import FetchCandidate, SourceConfig, SourceFetchResult, SourceHealth
from .registry import SourceRegistry

__all__ = [
    "FetchCandidate",
    "SourceConfig",
    "SourceFetchResult",
    "SourceHealth",
    "SourceRegistry",
    "load_source_registry",
    "load_source_health",
    "record_source_fetch",
    "save_source_health",
    "save_source_registry",
    "source_config_path",
]
