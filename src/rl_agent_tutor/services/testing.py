"""Exercise-session workflow service shared by CLI and Web API."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .. import examiner
from ..models import ExerciseAttempt, ExerciseQuestion, ExerciseSession, TrajectoryEntry
from ..store import append_exercise, append_trajectory, save_plan
from . import learning


@dataclass(frozen=True)
class TestSessionResult:
    session: ExerciseSession
    overall_score: float
    summary: str
    plan_state: str


def mark_self_testing() -> None:
    """Mark the active plan as currently self-testing."""
    ctx = learning.require_current_node()
    ctx.plan.state = "self_testing"
    save_plan(ctx.plan)


def submit_session(session: ExerciseSession) -> TestSessionResult:
    """Finalize and persist an exercise session, then update plan state."""
    avg, summary = examiner.summarize_session(session.attempts)
    session.overall_score = avg
    session.finished_at = session.finished_at or datetime.now().isoformat()
    append_exercise(session)
    append_trajectory(
        TrajectoryEntry(
            node_id=session.node_id,
            kind="test",
            content=summary,
            meta={"score": avg},
        )
    )

    plan = learning.require_plan()
    plan.state = "advancing" if avg >= 0.8 else "studying"
    save_plan(plan)

    return TestSessionResult(
        session=session,
        overall_score=avg,
        summary=summary,
        plan_state=plan.state,
    )


def submit_from_payload(
    node_id: str,
    questions: list[dict],
    attempts: list[dict],
) -> TestSessionResult:
    """Build and submit an exercise session from API-shaped dictionaries."""
    session = ExerciseSession(
        node_id=node_id,
        questions=[ExerciseQuestion(**q) for q in questions],
        attempts=[ExerciseAttempt(**a) for a in attempts],
        finished_at=datetime.now().isoformat(),
    )
    return submit_session(session)
