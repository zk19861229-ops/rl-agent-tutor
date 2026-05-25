"""Practice Agent — share industry best practices for the current node's topic."""
from __future__ import annotations
from .llm import chat
from .models import LearningNode


PRACTICE_SYSTEM = """You are a senior RL/LLM engineer who has shipped models at scale.
Share INDUSTRY BEST PRACTICES — not textbook content — for a given learning topic.

Style:
- Concrete, opinionated, battle-tested
- Cite real failure modes you've seen ("a common bug is...", "teams often discover...")
- Distinguish "must-do" from "nice-to-have"
- Prefer specific numbers, hyperparams, library choices
- Markdown, ≤ 600 words

LANGUAGE: write in 中文(Simplified Chinese). Keep technical terms, library names,
and code identifiers in English (e.g. "PPO", "TRL", "torch.compile") — do not translate them.
"""

PRACTICE_USER_TPL = """Topic:
- Node: {name}
- Description: {desc}
- Objectives: {objs}

Cover these angles:
1. **Top 3 must-dos** — things that consistently matter in production
2. **Top 3 common mistakes** — what teams get wrong, with the fix
3. **Tools/libs preferred by experienced practitioners** — and why
4. **A "from the trenches" insight** — one non-obvious lesson learned the hard way
"""


def best_practices(node: LearningNode) -> str:
    return chat(
        PRACTICE_SYSTEM,
        PRACTICE_USER_TPL.format(
            name=node.name, desc=node.description,
            objs=", ".join(node.objectives) or "(none)",
        ),
        max_tokens=3000, temperature=0.4,
    )
