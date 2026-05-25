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
from .models import LearningPlan, PlanState
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
    """Tell the learner what they should do next, based on plan state."""
    if normalize_state(plan):
        save_plan(plan)
    cur = plan.find_node(plan.current_node_id) if plan.current_node_id else None
    if plan.state == "done":
        return "🎉 Plan complete. Run `rl-agent review-stage` for a per-stage retrospective, or set a new goal with `rl-agent plan`."
    if not cur:
        return "Run `rl-agent plan \"<your goal>\"` to start."
    if plan.state == "studying":
        return (
            f"Current node: {cur.id} {cur.name}\n"
            f"  → fetch resources:  rl-agent fetch\n"
            f"  → ask the tutor:    rl-agent ask \"<your question>\"\n"
            f"  → industry tips:    rl-agent practices\n"
            f"  → when ready:       rl-agent test"
        )
    if plan.state == "self_testing":
        return (
            f"You're mid-test on {cur.id} {cur.name}.\n"
            f"  → resume / retake:  rl-agent test\n"
            f"  → mark complete:    rl-agent advance"
        )
    if plan.state == "advancing":
        return (
            f"You passed the test on {cur.id} {cur.name}.\n"
            f"  → confirm + move on: rl-agent advance\n"
            f"  → keep studying:     rl-agent ask \"...\"  (state will reset)"
        )
    return f"(unknown state: {plan.state})"

