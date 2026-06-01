"""Knowledge-base and review workflow service shared by CLI and Web API."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .. import archivist, reviewer
from ..archivist import _slugify
from ..config import workspace_path
from ..models import TrajectoryEntry
from ..store import append_trajectory
from . import learning


@dataclass(frozen=True)
class ArchiveResult:
    archived_files: list[Path]
    index_file: Path
    trajectory_node_id: str | None = None

    @property
    def all_files(self) -> list[Path]:
        return [*self.archived_files, self.index_file]


def archive(
    *,
    node_id: str | None = None,
    all_completed: bool = False,
    all_active: bool = False,
) -> ArchiveResult:
    """Archive node activity into Markdown KB files and rebuild the KB index."""
    plan = learning.require_plan()
    targets: list[Path]

    if all_completed:
        targets = archivist.archive_all(plan, only_completed=True)
        trajectory_node_id = None
    elif all_active:
        targets = archivist.archive_all(plan, only_completed=False)
        trajectory_node_id = None
    else:
        target_node_id = node_id or plan.current_node_id
        node = plan.find_node(target_node_id) if target_node_id else None
        if not node:
            raise learning.NodeNotFoundError(f"node {target_node_id} not found")
        stage = plan.stage_of(node.id)
        targets = [archivist.archive_node(node, stage_name=stage.name if stage else "")]
        trajectory_node_id = node_id

    index_file = archivist.build_index(plan)
    result = ArchiveResult(
        archived_files=targets,
        index_file=index_file,
        trajectory_node_id=trajectory_node_id,
    )
    append_trajectory(
        TrajectoryEntry(
            node_id=trajectory_node_id,
            kind="review",
            content=f"archived {len(result.all_files)} files",
        )
    )
    return result


def read_kb_index() -> str | None:
    learning.require_plan()
    index_file = workspace_path("library", "notes", "INDEX.md")
    if not index_file.exists():
        return None
    return index_file.read_text(encoding="utf-8")


def read_kb_node(node_id: str) -> str | None:
    plan = learning.require_plan()
    node = plan.find_node(node_id)
    if not node:
        raise learning.NodeNotFoundError(f"node {node_id} not found")
    target = workspace_path("library", "notes", f"{node.id}_{_slugify(node.name)}.md")
    if not target.exists():
        return None
    return target.read_text(encoding="utf-8")


def weekly_review() -> Path:
    plan = learning.require_plan()
    return reviewer.weekly_review(plan)


def stage_review(stage_id: int) -> Path:
    plan = learning.require_plan()
    return reviewer.stage_review(plan, stage_id)
