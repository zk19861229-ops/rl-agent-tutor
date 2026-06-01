"""Learning-plan workflow service.

This module owns plan-level state transitions that are shared by the CLI and
the FastAPI routes. Agent modules still own their domain logic; this layer keeps
persistence and trajectory side effects consistent across entrypoints.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..config import ensure_workspace
from ..models import LearningNode, LearningPlan, Stage, TrajectoryEntry
from .. import orchestrator, planner
from ..store import append_trajectory, load_plan, save_plan


class LearningServiceError(Exception):
    """Base exception for learning workflow failures."""


class PlanNotFoundError(LearningServiceError):
    """Raised when an operation requires an existing plan."""


class NodeNotFoundError(LearningServiceError):
    """Raised when a requested node id does not exist in the active plan."""


class NoCurrentNodeError(LearningServiceError):
    """Raised when a plan has no valid current node."""


@dataclass(frozen=True)
class PlanStatus:
    plan: LearningPlan
    next_action: str
    completed_nodes: int
    total_nodes: int

    @property
    def completion_percent(self) -> float:
        if self.total_nodes == 0:
            return 0.0
        return self.completed_nodes / self.total_nodes * 100


@dataclass(frozen=True)
class CurrentNodeContext:
    plan: LearningPlan
    node: LearningNode
    stage: Stage | None


@dataclass(frozen=True)
class AdvanceResult:
    plan: LearningPlan
    completed_node_id: str
    next_node_id: str | None


def plan_exists() -> bool:
    return load_plan() is not None


def require_plan() -> LearningPlan:
    plan = load_plan()
    if not plan:
        raise PlanNotFoundError("No plan found.")
    return plan


def require_current_node() -> CurrentNodeContext:
    plan = require_plan()
    if not plan.current_node_id:
        raise NoCurrentNodeError("No current node set.")
    node = plan.find_node(plan.current_node_id)
    if not node:
        raise NoCurrentNodeError(f"Current node {plan.current_node_id} not found in plan.")
    return CurrentNodeContext(plan=plan, node=node, stage=plan.stage_of(node.id))


def create_plan(goal: str, level: str = "") -> LearningPlan:
    ensure_workspace()
    new_plan = planner.make_plan(goal, level)
    save_plan(new_plan)
    append_trajectory(
        TrajectoryEntry(kind="plan", content=f"Goal: {goal}", meta={"level": level})
    )
    return new_plan


def get_plan_status() -> PlanStatus | None:
    plan = load_plan()
    if not plan:
        return None
    nodes = plan.all_nodes()
    completed = sum(1 for node in nodes if node.status == "completed")
    return PlanStatus(
        plan=plan,
        next_action=orchestrator.suggest_next_action(plan),
        completed_nodes=completed,
        total_nodes=len(nodes),
    )


def goto_node(node_id: str) -> LearningPlan:
    plan = require_plan()
    node = plan.find_node(node_id)
    if not node:
        raise NodeNotFoundError(f"node {node_id} not found")
    plan.current_node_id = node.id
    if node.status == "pending":
        node.status = "in_progress"
    plan.state = "studying"
    save_plan(plan)
    return plan


def advance_current_node() -> AdvanceResult:
    ctx = require_current_node()
    orchestrator.mark_node_completed(ctx.plan, ctx.node.id)
    next_node_id = orchestrator.advance_to_next(ctx.plan)
    append_trajectory(
        TrajectoryEntry(
            node_id=ctx.node.id,
            kind="advance",
            content=f"completed; next={next_node_id}",
        )
    )
    return AdvanceResult(
        plan=ctx.plan,
        completed_node_id=ctx.node.id,
        next_node_id=next_node_id,
    )
