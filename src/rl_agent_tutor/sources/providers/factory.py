"""Build source providers from registry configuration."""
from __future__ import annotations

from ..registry import SourceRegistry
from .base import SourceProvider
from .builtin import (
    ArxivProvider,
    GithubProvider,
    LocalDirectoryProvider,
    RssProvider,
    WebsiteProvider,
    YoutubeProvider,
)


def providers_for_registry(registry: SourceRegistry) -> list[SourceProvider]:
    provider_types = {
        "arxiv": ArxivProvider,
        "arxiv_query": ArxivProvider,
        "github": GithubProvider,
        "github_allowlist": GithubProvider,
        "website": WebsiteProvider,
        "rss": RssProvider,
        "youtube": YoutubeProvider,
        "youtube_playlist": YoutubeProvider,
        "youtube_channel": YoutubeProvider,
        "local_directory": LocalDirectoryProvider,
    }
    providers: list[SourceProvider] = []
    for source in registry.enabled_sources:
        provider_cls = provider_types.get(source.type)
        if provider_cls:
            providers.append(provider_cls(source))
    return providers
