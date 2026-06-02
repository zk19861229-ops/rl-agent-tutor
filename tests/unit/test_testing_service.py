from __future__ import annotations

from rl_agent_tutor.models import ExerciseAttempt, ExerciseQuestion, ExerciseSession, Resource
from rl_agent_tutor.services import testing
from rl_agent_tutor.store import append_resource, load_exercises, load_plan, load_resources, load_trajectory


def _session(score: float) -> ExerciseSession:
    question = ExerciseQuestion(qid="q1", type="concept", question="q")
    attempt = ExerciseAttempt(qid="q1", answer="a", score=score, feedback="missing concept")
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
    assert result.weak_areas[0]["dimension"] == "concept"
    assert load_plan().state == "studying"


def test_submit_session_marks_resources_tested(sample_plan):
    append_resource(Resource(node_id="0.1", kind="paper", title="Paper"))

    testing.submit_session(_session(0.9))

    resource = load_resources("0.1")[0]
    assert resource.status == "tested"
    assert resource.used_by[0].startswith("test:")
