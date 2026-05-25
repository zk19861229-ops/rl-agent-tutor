"""Tutor Agent — answer questions with full node context, with conversation memory.
RAG-enabled: when local PDF index is available, retrieves relevant passages and
asks the model to cite them.
"""
from __future__ import annotations
from .llm import chat_multi
from .models import LearningNode
from .store import load_trajectory
from . import rag


TUTOR_SYSTEM_TPL = """You are a private RL/LLM-post-training tutor for one specific learner.
The learner is currently working on this node:
- ID: {nid}
- Stage: {stage}
- Name: {name}
- Description: {desc}
- Objectives: {objs}

Style requirements:
- Direct answers, no "great question!" or filler
- If a concept has multiple readings, give the most common interpretation in one line, then ask which angle they want
- For code/math: explain idea first, then show code/formula
- Default ≤ 400 words; expand only when the question genuinely needs depth
- Prefer concrete over abstract: examples, numbers, comparisons
- Push back if the learner is asking the wrong question

LANGUAGE: respond in 中文(Simplified Chinese) by default. Keep technical terms in English
when that's how they appear in literature (e.g. "PPO", "advantage", "KL divergence", "GAE");
do NOT translate them. Code identifiers, library names, and paper titles stay in English.

CITATION POLICY (very important):
- If "Local library passages" is provided below, GROUND your answer in those passages.
- When you draw on a passage, append its citation tag like [doc_id · §section · p.N].
- If the passages don't actually answer the question, say so honestly and answer from
  general knowledge, prefixed with "(no library match)".
- Never invent citations. Only cite passages explicitly listed.
"""


def ask(node: LearningNode, stage_name: str, question: str,
        history_limit: int = 6, use_rag: bool = True) -> tuple[str, list[dict]]:
    """Returns (answer_text, citations_used)."""
    sys = TUTOR_SYSTEM_TPL.format(
        nid=node.id, stage=stage_name, name=node.name,
        desc=node.description, objs=", ".join(node.objectives) or "(none)",
    )

    citations: list[dict] = []
    if use_rag:
        hits = rag.retrieve(question, top_n=5, rerank=True)
        if hits:
            ctx_text, citations = rag.render_context(hits, max_chars=8000)
            sys += "\n\n## Local library passages\n" + ctx_text

    past = load_trajectory(node_id=node.id, limit=history_limit * 2)
    msgs: list[dict] = []
    for e in past:
        if e.kind == "ask":
            msgs.append({"role": "user", "content": e.content})
        elif e.kind == "answer":
            msgs.append({"role": "assistant", "content": e.content})
    msgs.append({"role": "user", "content": question})

    answer = chat_multi(sys, msgs, max_tokens=2000, temperature=0.4)
    return answer, citations
