from __future__ import annotations

from datetime import datetime

from rl_agent_tutor.models import ExerciseAttempt, ExerciseSession, Resource
from rl_agent_tutor.services import dashboard
from rl_agent_tutor.store import append_exercise, append_resource


def test_mastery_dashboard_counts_scores_resources_and_weak_nodes(sample_plan):
    append_resource(
        Resource(
            node_id="0.1",
            kind="paper",
            title="Paper",
            status="tested",
            used_by=["test:now"],
            priority="core",
        )
    )
    append_resource(Resource(node_id="0.2", kind="blog", title="Blog"))
    append_exercise(
        ExerciseSession(
            node_id="0.1",
            questions=[],
            attempts=[],
            finished_at=datetime.now().isoformat(),
            overall_score=0.9,
        )
    )

    stats = dashboard.build_mastery_dashboard(sample_plan)

    assert stats["mastery"]["avg_score"] == 0.9
    assert stats["mastery"]["solid_nodes"] == 1
    assert stats["resource_utilization"]["used"] == 1
    assert stats["resource_utilization"]["total"] == 2
    assert stats["plan_progress"]["total_nodes"] == 2
    assert stats["weak_nodes"][0]["node_id"] == "0.2"
    assert stats["recommended_action"]["id"] == "advance"


def test_mastery_dashboard_marks_used_unscored_node_developing(sample_plan):
    append_resource(
        Resource(
            node_id="0.1",
            kind="blog",
            title="Blog",
            status="read",
            used_by=["courseware:path"],
        )
    )

    stats = dashboard.build_mastery_dashboard(sample_plan)
    node = next(item for item in stats["nodes"] if item["node_id"] == "0.1")

    assert node["confidence"] == "developing"
    assert stats["recommended_action"]["id"] == "start_test"


def test_dashboard_aggregates_weak_areas(sample_plan):
    append_exercise(
        ExerciseSession(
            node_id="0.1",
            questions=[],
            attempts=[
                ExerciseAttempt(qid="q1", answer="a", score=0.4, feedback="代码实现 shape 错误")
            ],
            finished_at=datetime.now().isoformat(),
            overall_score=0.4,
        )
    )

    stats = dashboard.build_mastery_dashboard(sample_plan)

    assert stats["weak_areas"][0]["dimension"] == "code"
