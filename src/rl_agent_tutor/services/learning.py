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
from ..store import append_trajectory, load_exercises, load_plan, save_plan
from . import evidence, workflow


class LearningServiceError(Exception):
    """Base exception for learning workflow failures."""


class PlanNotFoundError(LearningServiceError):
    """Raised when an operation requires an existing plan."""


class NodeNotFoundError(LearningServiceError):
    """Raised when a requested node id does not exist in the active plan."""


class NoCurrentNodeError(LearningServiceError):
    """Raised when a plan has no valid current node."""


class AdvanceBlockedError(LearningServiceError):
    """Raised when the current node has not passed the advance gate."""

    def __init__(self, node_id: str, reasons: list[str]):
        self.node_id = node_id
        self.reasons = reasons
        super().__init__("; ".join(reasons))


@dataclass(frozen=True)
class PlanStatus:
    plan: LearningPlan
    next_action: str
    recommended_action: workflow.RecommendedAction
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
    gate: "AdvanceGate"


@dataclass(frozen=True)
class AdvanceGate:
    passed: bool
    reasons: list[str]
    latest_score: float | None
    evidence: dict
    forced: bool = False
    force_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "reasons": self.reasons,
            "latest_score": self.latest_score,
            "evidence": self.evidence,
            "forced": self.forced,
            "force_reason": self.force_reason,
        }


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
        next_action=workflow.suggest_next_action_text(plan),
        recommended_action=workflow.recommend_next_action(plan),
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


def evaluate_advance_gate(node_id: str) -> AdvanceGate:
    latest_score = _latest_score(node_id)
    summary = evidence.summarize_node(node_id)
    reasons: list[str] = []

    if latest_score is None:
        reasons.append("当前节点还没有完成自测。")
    elif latest_score < 0.8:
        reasons.append(f"最近一次自测分数 {latest_score:.2f} 低于 0.80。")

    if summary.total == 0:
        reasons.append("当前节点还没有抓取或登记学习资源。")
    elif summary.used == 0:
        reasons.append("当前节点资源还没有进入证据链，请先生成课件、引用、测试或归档。")

    return AdvanceGate(
        passed=not reasons,
        reasons=reasons,
        latest_score=latest_score,
        evidence=summary.to_dict(),
    )


def advance_current_node(*, force: bool = False, reason: str = "") -> AdvanceResult:
    ctx = require_current_node()
    gate = evaluate_advance_gate(ctx.node.id)
    force_reason = reason.strip()
    if gate.reasons and not force:
        raise AdvanceBlockedError(ctx.node.id, gate.reasons)
    if gate.reasons and force and not force_reason:
        raise AdvanceBlockedError(ctx.node.id, gate.reasons + ["覆盖推进需要填写原因。"])

    if force:
        gate = AdvanceGate(
            passed=not gate.reasons,
            reasons=gate.reasons,
            latest_score=gate.latest_score,
            evidence=gate.evidence,
            forced=True,
            force_reason=force_reason,
        )

    orchestrator.mark_node_completed(ctx.plan, ctx.node.id)
    next_node_id = orchestrator.advance_to_next(ctx.plan)
    append_trajectory(
        TrajectoryEntry(
            node_id=ctx.node.id,
            kind="advance",
            content=f"completed; next={next_node_id}; forced={gate.forced}",
            meta={"gate": gate.to_dict()},
        )
    )
    return AdvanceResult(
        plan=ctx.plan,
        completed_node_id=ctx.node.id,
        next_node_id=next_node_id,
        gate=gate,
    )


def _latest_score(node_id: str) -> float | None:
    sessions = [
        session
        for session in load_exercises(node_id=node_id)
        if session.overall_score is not None
    ]
    if not sessions:
        return None
    sessions.sort(key=lambda session: session.finished_at or session.started_at)
    return sessions[-1].overall_score
