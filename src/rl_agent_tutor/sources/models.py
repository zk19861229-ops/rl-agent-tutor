"""Models for configurable resource sources."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..models import Resource


SourceType = Literal[
    "arxiv",
    "github",
    "youtube",
    "youtube_playlist",
    "youtube_channel",
    "website",
    "rss",
    "local_directory",
    "arxiv_query",
    "github_allowlist",
]
SourcePriority = Literal["core", "normal", "supplemental"]
ResourceKind = Literal["paper", "code", "video", "blog", "note"]


class SourceConfig(BaseModel):
    id: str
    type: SourceType
    name: str
    enabled: bool = True
    priority: SourcePriority = "normal"
    config: dict = Field(default_factory=dict)

    def prompt_hint(self) -> str:
        details = []
        for key in ("url", "base_url", "query", "path", "repo", "channel_url"):
            value = self.config.get(key)
            if value:
                details.append(f"{key}={value}")
        tail = f" ({', '.join(details)})" if details else ""
        return f"- {self.id}: {self.name} [{self.type}, {self.priority}]{tail}"


class FetchCandidate(BaseModel):
    source_id: str
    kind: ResourceKind
    title: str
    url: str | None = None
    local_path: str | None = None
    relevance_score: float = 0.0
    reason: str = ""
    priority: SourcePriority = "normal"


class SourceFetchResult(BaseModel):
    source_id: str
    candidates: list[FetchCandidate] = Field(default_factory=list)
    resources: list[Resource] = Field(default_factory=list)
    error: str = ""


class SourceHealth(BaseModel):
    source_id: str
    ok: bool = True
    last_error: str = ""
    candidate_count: int = 0
    last_fetched_at: str = ""
