"""Examiner Agent — generate questions and grade answers for a node.

RAG-enabled: when generating questions, pulls relevant passages from the local
PDF library so questions can probe the actual material the learner has access to.
"""
from __future__ import annotations
from .llm import chat_json
from .models import LearningNode, ExerciseQuestion, ExerciseAttempt
from . import rag
from .config import EXAMINER_MODEL


EXAMINER_GEN_SYSTEM = """You write rigorous self-test questions for an RL/LLM learner.
Questions must distinguish real understanding from surface familiarity — probe causal
reasoning (why X works, what breaks if Y, how X compares to Z). Avoid trivia.

If "Local library excerpts" is provided, ground at least 2 questions in specifics
from those passages.

LANGUAGE: write the "question" and "expected_points" string values in 中文(Simplified Chinese).
Keep technical terms, library names, and code identifiers in English (e.g. "PPO", "GAE",
"clip ratio", "torch.nn"). JSON keys themselves stay English.

OUTPUT RULES (very important — output is parsed as JSON):
- Return ONE compact JSON object, no markdown fences, no prose around it.
- Inside string fields, write real newlines as the two characters \\n (backslash + n).
- For code-debug questions: keep the snippet small (≤ 12 lines). Write it as one
  string with \\n separators, NOT a real fenced block.
- Keep each question text ≤ 400 chars when possible.
"""

EXAMINER_GEN_USER_TPL = """Node:
- ID: {nid}
- Name: {name}
- Description: {desc}
- Objectives: {objs}

{rag_block}

Return EXACTLY this JSON shape:
{{
  "questions": [
    {{"qid":"q1","type":"concept","question":"...","expected_points":["...","..."]}},
    {{"qid":"q2","type":"concept","question":"...","expected_points":["..."]}},
    {{"qid":"q3","type":"derivation","question":"...","expected_points":["..."]}},
    {{"qid":"q4","type":"code-debug","question":"...","expected_points":["..."]}},
    {{"qid":"q5","type":"discussion","question":"...","expected_points":["..."]}}
  ]
}}

Output the JSON object only."""


EXAMINER_GRADE_SYSTEM = """You are a strict but fair grader for an RL learner.
Given a question, the points it should cover, and the learner's answer:
- Score 0.0–1.0 (be calibrated; a partial answer that misses key points should be ≤ 0.6)
- Identify what's correct, what's missing, what's wrong
- Give one concrete next action the learner should take
"""

EXAMINER_GRADE_USER = """Question ({type}):
{q}

Expected key points:
{points}

Learner's answer:
{a}

Output JSON:
{{
  "score": 0.0,
  "feedback": "<≤200 words, structured: ✅ correct ... ⚠️ missing ... ❌ wrong ... 👉 next: ...>"
}}
JSON only."""


def generate_exercises(node: LearningNode, use_rag: bool = True) -> list[ExerciseQuestion]:
    rag_block = ""
    if use_rag:
        # use the node name + objectives as the retrieval query
        query = f"{node.name}. {node.description}. " + " ".join(node.objectives)
        ctx, _, _ = rag.with_rag(query, top_n=4, max_chars=6000)
        if ctx:
            rag_block = "## Local library excerpts\n" + ctx

    kwargs = {"model": EXAMINER_MODEL} if EXAMINER_MODEL else {}
    raw = chat_json(EXAMINER_GEN_SYSTEM, EXAMINER_GEN_USER_TPL.format(
        nid=node.id, name=node.name, desc=node.description,
        objs=", ".join(node.objectives) or "(none)",
        rag_block=rag_block,
    ), max_tokens=2800, **kwargs)
    return [ExerciseQuestion(**q) for q in raw.get("questions", [])]


def grade_answer(q: ExerciseQuestion, answer: str) -> ExerciseAttempt:
    kwargs = {"model": EXAMINER_MODEL} if EXAMINER_MODEL else {}
    raw = chat_json(EXAMINER_GRADE_SYSTEM, EXAMINER_GRADE_USER.format(
        type=q.type, q=q.question,
        points="\n".join(f"- {p}" for p in q.expected_points),
        a=answer or "(no answer provided)",
    ), max_tokens=900, **kwargs)
    score = float(raw.get("score", 0.0))
    score = max(0.0, min(1.0, score))
    return ExerciseAttempt(qid=q.qid, answer=answer, score=score, feedback=raw.get("feedback", ""))


def summarize_session(attempts: list[ExerciseAttempt]) -> tuple[float, str]:
    if not attempts:
        return 0.0, "(no attempts)"
    avg = sum(a.score for a in attempts) / len(attempts)
    weak = [a.qid for a in attempts if a.score < 0.6]
    if avg >= 0.8:
        verdict = "✅ Strong understanding. Ready to advance."
    elif avg >= 0.6:
        verdict = "⚠️ Decent grasp, but revisit weak points before advancing."
    else:
        verdict = "❌ Significant gaps. Recommend re-studying before testing again."
    return avg, f"Score: {avg:.2f}. Weak qids: {weak or 'none'}. {verdict}"
