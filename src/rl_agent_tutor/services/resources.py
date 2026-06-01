"""Resource workflow service shared by CLI and Web API."""
from __future__ import annotations

from dataclasses import dataclass

from .. import librarian
from ..config import workspace_path
from ..models import Resource, TrajectoryEntry
from ..store import append_resource, append_trajectory, load_resources
from . import learning


@dataclass(frozen=True)
class FetchResult:
    node_id: str
    resources: list[Resource]


def fetch_for_current_node() -> FetchResult:
    """Fetch recommended resources for the current node and record trajectory."""
    ctx = learning.require_current_node()
    resources = librarian.fetch_for_node(ctx.node)
    append_trajectory(
        TrajectoryEntry(
            node_id=ctx.node.id,
            kind="fetch",
            content=f"fetched {len(resources)} resources",
        )
    )
    return FetchResult(node_id=ctx.node.id, resources=resources)


def list_node_resources(node_id: str | None = None) -> list[Resource]:
    if node_id is None:
        ctx = learning.require_current_node()
        node_id = ctx.node.id
    return load_resources(node_id=node_id)


def fetch_blog_for_current_node(url: str, why: str = "") -> Resource | None:
    ctx = learning.require_current_node()
    blogs_dir = workspace_path("library", "notes", "blogs")
    resource = librarian.fetch_blog_resource(
        url=url,
        why=why,
        node_id=ctx.node.id,
        blogs_dir=blogs_dir,
    )
    if resource is not None:
        append_resource(resource)
    return resource


def fetch_youtube_for_current_node(
    url_or_id: str,
    *,
    title: str = "",
    why: str = "",
) -> Resource | None:
    ctx = learning.require_current_node()
    transcripts_dir = workspace_path("library", "notes", "transcripts")
    resource = librarian.fetch_youtube_resource(
        url_or_id=url_or_id,
        title=title,
        why=why,
        node_id=ctx.node.id,
        transcripts_dir=transcripts_dir,
    )
    if resource is not None:
        append_resource(resource)
    return resource
