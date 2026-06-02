"""Knowledge-base and review workflow service shared by CLI and Web API."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .. import archivist, reviewer
from ..archivist import _slugify
from ..config import workspace_path
from ..models import LearningNode, Stage, TrajectoryEntry
from ..store import append_trajectory, save_plan
from . import evidence
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
        for node in plan.all_nodes():
            if node.status == "completed":
                evidence.mark_node_resources(
                    node.id,
                    status="archived",
                    used_by="archive:all_completed",
                )
    elif all_active:
        targets = archivist.archive_all(plan, only_completed=False)
        trajectory_node_id = None
        for node in plan.all_nodes():
            evidence.mark_node_resources(
                node.id,
                status="archived",
                used_by="archive:all_active",
            )
    else:
        target_node_id = node_id or plan.current_node_id
        node = plan.find_node(target_node_id) if target_node_id else None
        if not node:
            raise learning.NodeNotFoundError(f"node {target_node_id} not found")
        stage = plan.stage_of(node.id)
        targets = [archivist.archive_node(node, stage_name=stage.name if stage else "")]
        trajectory_node_id = node_id
        evidence.mark_node_resources(
            node.id,
            status="archived",
            used_by=f"archive:{targets[0].name if targets else node.id}",
        )

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


def apply_latest_weekly_review() -> dict:
    plan = learning.require_plan()
    review = _latest_review_file("weekly_*.md")
    if not review:
        return {"applied": 0, "message": "no weekly review found", "nodes": []}
    markdown = review.read_text(encoding="utf-8")
    suggestions = _extract_review_suggestions(markdown)
    if not suggestions:
        return {"applied": 0, "message": "no actionable suggestions found", "nodes": []}

    added_nodes: list[LearningNode] = []
    updated_nodes: list[str] = []
    reordered: list[str] = []
    estimate_updates: list[str] = []
    for suggestion in suggestions[:8]:
        action = _apply_review_suggestion(plan, suggestion)
        if action["type"] == "add":
            added_nodes.append(action["node"])
        elif action["type"] == "update":
            updated_nodes.append(action["node_id"])
        elif action["type"] == "reorder":
            reordered.append(action["node_id"])
        if action.get("estimated"):
            estimate_updates.append(action["node_id"])

    stage = None
    if added_nodes:
        stage_id = max((stage.id for stage in plan.stages), default=-1) + 1
        stage = Stage(
            id=stage_id,
            name="复盘调整",
            description=f"Applied from {review.name}",
            nodes=[
                node.model_copy(update={"id": f"{stage_id}.{index}"})
                for index, node in enumerate(added_nodes, start=1)
            ],
        )
        plan.stages.append(stage)
    if not plan.current_node_id:
        plan.current_node_id = stage.nodes[0].id if stage and stage.nodes else None
    plan.state = "studying"
    save_plan(plan)
    added_ids = [node.id for node in stage.nodes] if stage else []
    append_trajectory(
        TrajectoryEntry(
            kind="review",
            content=(
                f"applied weekly review {review.name}: "
                f"{len(added_ids)} added, {len(updated_nodes)} updated, {len(reordered)} reordered"
            ),
            meta={
                "review": str(review),
                "added_nodes": added_ids,
                "updated_nodes": updated_nodes,
                "reordered_nodes": reordered,
                "estimated_nodes": estimate_updates,
            },
        )
    )
    return {
        "applied": len(added_ids) + len(updated_nodes) + len(reordered),
        "review": str(review),
        "nodes": [node.model_dump() for node in stage.nodes] if stage else [],
        "updated_nodes": updated_nodes,
        "reordered_nodes": reordered,
        "estimated_nodes": estimate_updates,
        "plan": plan.model_dump(),
    }


def stage_review(stage_id: int) -> Path:
    plan = learning.require_plan()
    return reviewer.stage_review(plan, stage_id)


def _latest_review_file(pattern: str) -> Path | None:
    review_dir = workspace_path("library", "notes", "reviews")
    files = sorted(review_dir.glob(pattern), key=lambda path: path.stat().st_mtime)
    return files[-1] if files else None


def _extract_review_suggestions(markdown: str) -> list[str]:
    suggestions: list[str] = []
    capture = False
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            capture = any(token in line for token in ("建议", "下一步", "调整", "行动"))
            continue
        if not capture:
            continue
        match = re.match(r"^(?:[-*]|\d+[.)])\s+(.+)$", line)
        if not match:
            continue
        item = re.sub(r"\s+", " ", match.group(1)).strip()
        if item and item not in suggestions:
            suggestions.append(item)
    return suggestions


def _apply_review_suggestion(plan, suggestion: str) -> dict:
    node_id = _suggestion_node_id(suggestion)
    node = plan.find_node(node_id) if node_id else None
    estimated = _suggested_hours(suggestion)

    if node:
        updates: dict = {}
        if estimated:
            updates["estimated_hours"] = estimated
        note = f"Weekly review suggestion: {suggestion}"
        updates["notes"] = (node.notes + "\n" + note).strip() if node.notes else note
        updated = node.model_copy(update=updates)
        _replace_node(plan, updated)
        reordered = _apply_reorder(plan, node_id, suggestion)
        if reordered:
            return {"type": "reorder", "node_id": node_id, "estimated": bool(estimated)}
        return {"type": "update", "node_id": node_id, "estimated": bool(estimated)}

    new_node = LearningNode(
        id="pending",
        name=_clean_suggestion_title(suggestion),
        description=suggestion,
        objectives=["完成复盘建议并验证是否改善学习闭环。"],
        estimated_hours=estimated or (0.5, 1.5),
    )
    return {"type": "add", "node": new_node, "node_id": "", "estimated": bool(estimated)}


def _suggestion_node_id(text: str) -> str:
    explicit = re.search(r"\[(?:update|reorder|estimate):\s*([0-9]+\.[0-9]+)\]", text, re.I)
    if explicit:
        return explicit.group(1)
    match = re.search(r"\b([0-9]+\.[0-9]+)\b", text)
    return match.group(1) if match else ""


def _suggested_hours(text: str) -> tuple[float, float] | None:
    range_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*[-~]\s*([0-9]+(?:\.[0-9]+)?)\s*(?:h|小时)", text, re.I)
    if range_match:
        return float(range_match.group(1)), float(range_match.group(2))
    single = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:h|小时)", text, re.I)
    if single:
        value = float(single.group(1))
        return value, value
    return None


def _replace_node(plan, updated: LearningNode) -> None:
    for stage in plan.stages:
        for index, node in enumerate(stage.nodes):
            if node.id == updated.id:
                stage.nodes[index] = updated
                return


def _apply_reorder(plan, node_id: str, suggestion: str) -> bool:
    before = re.search(r"\bbefore\s+([0-9]+\.[0-9]+)\b", suggestion, re.I)
    after = re.search(r"\bafter\s+([0-9]+\.[0-9]+)\b", suggestion, re.I)
    if not before and not after and not any(token in suggestion for token in ("提前", "优先", "前置", "先学")):
        return False
    stage = plan.stage_of(node_id)
    if not stage:
        return False
    moving = None
    for index, node in enumerate(stage.nodes):
        if node.id == node_id:
            moving = stage.nodes.pop(index)
            break
    if not moving:
        return False
    target_id = before.group(1) if before else after.group(1) if after else ""
    insert_at = 0
    if target_id:
        for index, node in enumerate(stage.nodes):
            if node.id == target_id:
                insert_at = index + (1 if after else 0)
                break
    stage.nodes.insert(insert_at, moving)
    return True


def _clean_suggestion_title(suggestion: str) -> str:
    text = re.sub(r"\[(?:update|reorder|estimate):[^\]]+\]", "", suggestion, flags=re.I)
    text = re.sub(r"\b[0-9]+\.[0-9]+\b", "", text)
    text = re.sub(r"\s+", " ", text).strip(" -:：")
    return text[:48] or "复盘改进任务"
