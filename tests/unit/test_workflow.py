from __future__ import annotations

from datetime import datetime

from rl_agent_tutor.models import ExerciseAttempt, ExerciseSession, Resource
from rl_agent_tutor.services import evidence, workflow
from rl_agent_tutor.store import append_exercise, append_resource


def test_recommend_fetch_when_node_has_no_resources(sample_plan):
    action = workflow.recommend_next_action(sample_plan)

    assert action.id == "fetch_resources"
    assert action.primary_endpoint == "/api/fetch"


def test_recommend_courseware_when_resources_are_unused(sample_plan):
    append_resource(Resource(node_id="0.1", kind="blog", title="Blog"))

    action = workflow.recommend_next_action(sample_plan)

    assert action.id == "generate_courseware"


def test_recommend_test_after_resources_enter_evidence_chain(sample_plan):
    append_resource(Resource(node_id="0.1", kind="blog", title="Blog"))
    evidence.mark_node_resources("0.1", status="read", used_by="courseware:path")

    action = workflow.recommend_next_action(sample_plan)

    assert action.id == "start_test"
    assert action.view == "test"


def test_recommend_remediation_after_low_score(sample_plan):
    append_resource(Resource(node_id="0.1", kind="blog", title="Blog", status="read", used_by=["courseware:path"]))
    append_exercise(
        ExerciseSession(
            node_id="0.1",
            questions=[],
            attempts=[],
            finished_at=datetime.now().isoformat(),
            overall_score=0.4,
        )
    )

    action = workflow.recommend_next_action(sample_plan)

    assert action.id == "remediate"
    assert "0.40" in action.reason


def test_recommend_advance_after_high_score(sample_plan):
    append_resource(Resource(node_id="0.1", kind="blog", title="Blog", status="tested", used_by=["test:now"]))
    append_exercise(
        ExerciseSession(
            node_id="0.1",
            questions=[],
            attempts=[],
            finished_at=datetime.now().isoformat(),
            overall_score=0.9,
        )
    )

    action = workflow.recommend_next_action(sample_plan)

    assert action.id == "advance"


def test_generate_remediation_package_for_low_score(sample_plan):
    append_exercise(
        ExerciseSession(
            node_id="0.1",
            questions=[],
            attempts=[
                ExerciseAttempt(qid="q1", answer="bad", score=0.3, feedback="missing concept")
            ],
            finished_at=datetime.now().isoformat(),
            overall_score=0.3,
        )
    )

    result = workflow.generate_remediation_package(sample_plan.find_node("0.1"))

    assert result["latest_score"] == 0.3
    assert "补弱" in result["markdown"]
    assert result["tasks"]
