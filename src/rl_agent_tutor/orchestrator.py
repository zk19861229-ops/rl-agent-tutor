"""Orchestrator — the state machine that drives the learning loop.

States: planning → studying → self_testing → reviewing → advancing → done
The orchestrator decides what should happen next given current state and recent activity.
"""
from __future__ import annotations
from datetime import datetime
from .models import LearningPlan, PlanState
from .store import save_plan, load_plan


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
    cur = plan.find_node(plan.current_node_id) if plan.current_node_id else None
    if plan.state == "done":
        return "🎉 Plan complete. Run `rl-agent review` to generate a final retrospective, or set a new goal with `rl-agent plan`."
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
        return f"You're mid-test on {cur.id}. Run `rl-agent test --resume` or `rl-agent advance` if done."
    if plan.state == "advancing":
        return "Run `rl-agent advance` to move to the next node."
    return "(unknown state)"
