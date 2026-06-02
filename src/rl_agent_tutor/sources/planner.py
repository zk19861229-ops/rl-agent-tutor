"""LLM planning for source fetches."""
from __future__ import annotations

from ..llm import chat_json
from ..models import LearningNode
from .registry import SourceRegistry


LIBRARIAN_SYSTEM = """You are a research librarian for RL/LLM topics.
For a given learning node, suggest the best resources to fetch from each source.
Be specific: actual paper titles, real arxiv search terms, real GitHub repos, real blog URLs, real YouTube video IDs/URLs.
Only suggest things you are confident exist. If you are not sure, omit it rather than guess.
"""

LIBRARIAN_USER = """Learning node:
- ID: {nid}
- Name: {name}
- Description: {desc}
- Objectives: {objs}

Enabled source guide:
{source_hints}

Field guide:
- arxiv_queries: 2-4 specific arxiv queries (paper titles or "author year topic")
- github_repos: 1-2 high-quality "owner/repo" identifiers
- blog_urls: 1-3 high-signal blog/article URLs, each {{"url": "...", "why": "<one line>"}}
- youtube_videos: 0-2 lecture/talk videos, each {{"url_or_id": "...", "title": "...", "why": "..."}}

Return EXACTLY this JSON shape (no comments, no trailing commas):
{{
  "arxiv_queries": ["...", "..."],
  "github_repos": ["owner/repo"],
  "blog_urls": [
    {{"url": "https://...", "why": "..."}}
  ],
  "youtube_videos": [
    {{"url_or_id": "https://youtube.com/watch?v=... or 11-char id", "title": "...", "why": "..."}}
  ]
}}
Output JSON only."""


def plan_source_fetches(node: LearningNode, registry: SourceRegistry) -> dict:
    user = LIBRARIAN_USER.format(
        nid=node.id,
        name=node.name,
        desc=node.description,
        objs=", ".join(node.objectives) or "(none)",
        source_hints=registry.prompt_hints(),
    )
    return chat_json(LIBRARIAN_SYSTEM, user)
