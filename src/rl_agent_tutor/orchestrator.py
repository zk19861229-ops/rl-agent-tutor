"""Orchestrator — the state machine that drives the learning loop.

States: planning → studying → self_testing → advancing → done

`reviewing` was specced but never wired up; it is accepted for backwards-compat
on existing plan.json files but is normalized to `studying` on load.
`advancing` is a transient state — `mark_node_completed`+`advance_to_next` flips
it back to `studying` immediately. If we observe a plan resting in `advancing`
(e.g. user ran `test` then quit before `advance`), `suggest_next_action` calls
that out explicitly instead of leaving the loop wedged.
"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from .config import workspace_path
from .models import LearningPlan, PlanState, Stage
from .store import save_plan, load_plan


def normalize_state(plan: LearningPlan) -> bool:
    """Coerce dead/legacy states. Returns True if anything changed."""
    if plan.state == "reviewing":
        plan.state = "studying"
        return True
    return False


def transition(plan: LearningPlan, new_state: PlanState) -> None:
    plan.state = new_state
    save_plan(plan)


def mark_node_completed(plan: LearningPlan, node_id: str) -> None:
    n = plan.find_node(node_id)
    if not n:
        return
    n.status = "completed"
    n.completed_at = datetime.now().isoformat()
    save_plan(plan)


def stage_just_completed(plan: LearningPlan, node_id: str) -> Stage | None:
    """If `node_id` was the LAST pending node in its stage, return the stage.

    Used by callers (CLI advance, web /api/advance) to fire the Reviewer
    stage_review automatically. Returns None if the stage already had a
    review file on disk, so we don't double-fire.
    """
    s = plan.stage_of(node_id)
    if not s or not s.nodes:
        return None
    if not all(n.status == "completed" for n in s.nodes):
        return None
    existing = workspace_path("library", "notes", "reviews").glob(f"stage_{s.id}_*.md")
    if any(existing):
        return None
    return s


def advance_to_next(plan: LearningPlan) -> str | None:
    """Move current_node_id to the next pending node. Returns new node id or None."""
    nxt = plan.next_pending_node()
    if not nxt:
        plan.state = "done"
        save_plan(plan)
        return None
    plan.current_node_id = nxt.id
    nxt.status = "in_progress"
    plan.state = "studying"
    save_plan(plan)
    return nxt.id


def suggest_next_action(plan: LearningPlan) -> str:
    """Compatibility wrapper. Learner-facing recommendations live in workflow."""
    if normalize_state(plan):
        save_plan(plan)
    from .services import workflow

    return workflow.suggest_next_action_text(plan)
