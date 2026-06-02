"""Provider protocol for configurable source fetchers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ...models import LearningNode, Resource
from ..models import SourceConfig, SourceFetchResult


class SourceProvider(ABC):
    def __init__(self, source: SourceConfig):
        self.source = source

    @abstractmethod
    def fetch(
        self,
        node: LearningNode,
        plan_json: dict,
        dirs: dict[str, Path],
    ) -> SourceFetchResult:
        """Fetch resources for one source."""

    def tag(self, resource: Resource) -> Resource:
        resource.source_id = self.source.id
        resource.priority = self.source.priority
        return resource
