from __future__ import annotations

from rl_agent_tutor.models import ExerciseAttempt, ExerciseQuestion, ExerciseSession
from rl_agent_tutor.services import testing
from rl_agent_tutor.store import load_exercises, load_plan, load_trajectory


def _session(score: float) -> ExerciseSession:
    question = ExerciseQuestion(qid="q1", type="concept", question="q")
    attempt = ExerciseAttempt(qid="q1", answer="a", score=score, feedback="f")
    return ExerciseSession(node_id="0.1", questions=[question], attempts=[attempt])


def test_mark_self_testing_updates_plan(sample_plan):
    testing.mark_self_testing()

    assert load_plan().state == "self_testing"


def test_submit_session_persists_and_advances_on_high_score(sample_plan):
    result = testing.submit_session(_session(0.9))

    assert result.overall_score == 0.9
    assert result.plan_state == "advancing"
    assert load_plan().state == "advancing"
    assert load_exercises("0.1")[0].overall_score == 0.9
    assert load_trajectory("0.1")[-1].kind == "test"


def test_submit_session_keeps_studying_on_low_score(sample_plan):
    result = testing.submit_session(_session(0.5))

    assert result.plan_state == "studying"
    assert load_plan().state == "studying"
