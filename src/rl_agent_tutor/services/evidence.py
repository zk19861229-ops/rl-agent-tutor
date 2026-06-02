"""Resource evidence tracking.

Resources start as fetched artifacts. As they are used by courseware, tutor
citations, tests, and archive generation, this service records lifecycle state
and a compact `used_by` trail.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..models import Resource
from ..store import load_resources, save_resources


ResourceStatus = Literal[
    "recommended",
    "fetched",
    "read",
    "cited",
    "tested",
    "archived",
    "rejected",
]

_STATUS_RANK = {
    "recommended": 0,
    "fetched": 1,
    "read": 2,
    "cited": 3,
    "tested": 4,
    "archived": 5,
    "rejected": 99,
}


@dataclass(frozen=True)
class EvidenceSummary:
    node_id: str
    total: int
    by_status: dict[str, int]
    by_priority: dict[str, int]
    used: int

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "total": self.total,
            "by_status": self.by_status,
            "by_priority": self.by_priority,
            "used": self.used,
        }


def mark_node_resources(
    node_id: str,
    *,
    status: ResourceStatus,
    used_by: str,
    only_with_local_content: bool = False,
) -> list[Resource]:
    """Mark resources for a node as used by a workflow step.

    Status only moves forward, except `rejected`, which is terminal. This keeps
    an archived resource from being downgraded if a later courseware read runs.
    """
    all_resources = load_resources()
    changed = False
    updated: list[Resource] = []
    touched: list[Resource] = []

    for resource in all_resources:
        if resource.node_id != node_id:
            updated.append(resource)
            continue
        if only_with_local_content and not resource.local_path:
            updated.append(resource)
            continue

        new_status = _max_status(resource.status, status)
        used_by_items = list(resource.used_by)
        if used_by and used_by not in used_by_items:
            used_by_items.append(used_by)
        if new_status != resource.status or used_by_items != resource.used_by:
            resource = resource.model_copy(
                update={"status": new_status, "used_by": used_by_items}
            )
            changed = True
        touched.append(resource)
        updated.append(resource)

    if changed:
        save_resources(updated)
    return touched


def summarize_node(node_id: str) -> EvidenceSummary:
    resources = load_resources(node_id=node_id)
    by_status: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    used = 0
    for resource in resources:
        by_status[resource.status] = by_status.get(resource.status, 0) + 1
        by_priority[resource.priority] = by_priority.get(resource.priority, 0) + 1
        if resource.used_by:
            used += 1
    return EvidenceSummary(
        node_id=node_id,
        total=len(resources),
        by_status=by_status,
        by_priority=by_priority,
        used=used,
    )


def _max_status(current: str, incoming: ResourceStatus) -> ResourceStatus:
    if current == "rejected":
        return "rejected"
    current_rank = _STATUS_RANK.get(current, 0)
    incoming_rank = _STATUS_RANK[incoming]
    return incoming if incoming_rank > current_rank else current  # type: ignore[return-value]
