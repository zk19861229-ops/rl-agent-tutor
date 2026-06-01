from __future__ import annotations

import pytest

from rl_agent_tutor import config
from rl_agent_tutor.models import LearningNode, LearningPlan, Stage
from rl_agent_tutor.store import save_plan


@pytest.fixture
def workspace(tmp_path):
    config.set_active_workspace(tmp_path)
    config.ensure_workspace()
    return tmp_path


@pytest.fixture
def sample_plan(workspace):
    plan = LearningPlan(
        goal="goal",
        starting_level="level",
        state="studying",
        current_node_id="0.1",
        stages=[
            Stage(
                id=0,
                name="Stage",
                nodes=[
                    LearningNode(id="0.1", name="First", description="first"),
                    LearningNode(id="0.2", name="Second", description="second"),
                ],
            )
        ],
    )
    save_plan(plan)
    return plan
