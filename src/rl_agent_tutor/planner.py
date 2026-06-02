"""Planner Agent — given a goal, produce a structured learning plan."""
from __future__ import annotations
from .llm import chat_json
from .models import LearningPlan, Stage, LearningNode
from .config import PLANNER_MODEL


PLANNER_SYSTEM = """You are a senior RL/LLM post-training researcher and learning coach.
Given a learner's goal and current level, you produce a STRUCTURED, EXECUTABLE learning plan.

Hard rules:
- Each node MUST have a verifiable deliverable (code / notes / curve / written explanation), not just "understand X".
- Stages should follow logical prerequisite order. Earlier stages set up context for later ones.
- Estimated hours should reflect realistic part-time effort (10–15 hrs/week).
- Be opinionated. Prefer fewer, deeper nodes over a long shallow list.
- Respond in the language the learner used in their goal.
"""


PLANNER_USER_TEMPLATE = """Learner's goal:
{goal}

Current level / background:
{level}

Produce a learning plan as JSON with this exact schema:
{{
  "goal": "<echo of goal>",
  "starting_level": "<echo of level>",
  "stages": [
    {{
      "id": 0,
      "name": "<short name>",
      "description": "<one paragraph why this stage exists>",
      "nodes": [
        {{
          "id": "0.1",
          "name": "<short>",
          "description": "<one sentence>",
          "objectives": ["<verifiable deliverable 1>", "<deliverable 2>"],
          "estimated_hours": [<min>, <max>]
        }}
      ]
    }}
  ]
}}

Constraints:
- 4 to 6 stages
- 3 to 5 nodes per stage
- Node ids must be "<stage>.<index>" e.g. "2.3"
- Output JSON only.
"""


def make_plan(goal: str, level: str = "") -> LearningPlan:
    user = PLANNER_USER_TEMPLATE.format(goal=goal, level=level or "(not specified)")
    kwargs = {"model": PLANNER_MODEL} if PLANNER_MODEL else {}
    raw = chat_json(PLANNER_SYSTEM, user, max_tokens=4200, **kwargs)
    stages: list[Stage] = []
    for s in raw.get("stages", []):
        nodes = [
            LearningNode(
                id=str(n["id"]),
                name=n["name"],
                description=n.get("description", ""),
                objectives=n.get("objectives", []),
                estimated_hours=tuple(n.get("estimated_hours", [1, 3])),
            )
            for n in s.get("nodes", [])
        ]
        stages.append(
            Stage(
                id=int(s["id"]),
                name=s["name"],
                description=s.get("description", ""),
                nodes=nodes,
            )
        )
    plan = LearningPlan(
        goal=raw.get("goal", goal),
        starting_level=raw.get("starting_level", level),
        stages=stages,
        state="planning",
    )
    if plan.all_nodes():
        plan.current_node_id = plan.all_nodes()[0].id
        plan.state = "studying"
    return plan
