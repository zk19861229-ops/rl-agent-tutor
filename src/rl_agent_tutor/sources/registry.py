"""Registry for enabled resource sources."""
from __future__ import annotations

from collections.abc import Iterable

from .models import SourceConfig


class SourceRegistry:
    def __init__(self, sources: Iterable[SourceConfig]):
        self._sources = list(sources)

    @property
    def sources(self) -> list[SourceConfig]:
        return list(self._sources)

    @property
    def enabled_sources(self) -> list[SourceConfig]:
        return [source for source in self._sources if source.enabled]

    def enabled_types(self) -> set[str]:
        return {source.type for source in self.enabled_sources}

    def prompt_hints(self) -> str:
        enabled = self.enabled_sources
        if not enabled:
            return "- no sources enabled"
        return "\n".join(source.prompt_hint() for source in enabled)

    def source_for_kind(self, kind: str) -> SourceConfig | None:
        preferred = {
            "paper": ("arxiv", "arxiv_query", "local_directory"),
            "code": ("github", "github_allowlist", "local_directory"),
            "video": ("youtube", "youtube_playlist", "youtube_channel"),
            "blog": ("website", "rss"),
            "note": ("local_directory",),
        }.get(kind, ())
        for source_type in preferred:
            for source in self.enabled_sources:
                if source.type == source_type:
                    return source
        return None
