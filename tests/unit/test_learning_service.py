from __future__ import annotations

from rl_agent_tutor.models import LearningNode, LearningPlan, Stage
from rl_agent_tutor.services import learning
from rl_agent_tutor.store import load_plan, load_trajectory


def test_create_plan_saves_plan_and_trajectory(workspace, monkeypatch):
    def fake_make_plan(goal: str, level: str = ""):
        return LearningPlan(
            goal=goal,
            starting_level=level,
            state="studying",
            current_node_id="0.1",
            stages=[
                Stage(
                    id=0,
                    name="Stage",
                    nodes=[LearningNode(id="0.1", name="Node", description="")],
                )
            ],
        )

    monkeypatch.setattr(learning.planner, "make_plan", fake_make_plan)

    plan = learning.create_plan("learn", "beginner")

    assert plan.goal == "learn"
    assert load_plan().goal == "learn"
    entries = load_trajectory(limit=5)
    assert [entry.kind for entry in entries] == ["plan"]
    assert entries[0].meta == {"level": "beginner"}


def test_goto_node_updates_current_node(sample_plan):
    plan = learning.goto_node("0.2")

    assert plan.current_node_id == "0.2"
    assert plan.find_node("0.2").status == "in_progress"
    assert load_plan().current_node_id == "0.2"


def test_advance_current_node_marks_done_and_records_trajectory(sample_plan):
    result = learning.advance_current_node()

    assert result.completed_node_id == "0.1"
    assert result.next_node_id == "0.2"
    assert result.plan.find_node("0.1").status == "completed"
    assert load_trajectory(limit=1)[0].kind == "advance"
