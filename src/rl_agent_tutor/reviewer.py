"""Reviewer Agent — generate weekly / stage retrospectives.

Weekly review: aggregate trajectory + exercises across the last 7 days, summarize
what was learned, identify weak spots, recommend next focus.

Stage review: triggered when all nodes in a stage are completed; produces a more
substantial retrospective with knowledge-map suggestions.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path
from .llm import chat
from .models import LearningPlan
from .store import load_trajectory, load_exercises
from .config import REVIEWER_MODEL, workspace_path


WEEKLY_SYSTEM = """You are a thoughtful learning coach.
Given the learner's recent activity (last 7 days), produce a CONCISE retrospective:
- What they actually learned (not what they were supposed to learn)
- Weak spots evidenced by exercise scores or repeated questions
- 2–3 specific recommendations for the coming week
- One pointed observation: a pattern they may not have noticed themselves

Style: Markdown, ≤600 words, direct. No fluff.

LANGUAGE: write in 中文(Simplified Chinese). Keep technical terms and library
names in English (e.g. "PPO", "TRL", "GAE"). Section headings should also be 中文.
"""


WEEKLY_USER_TPL = """Goal: {goal}

Current node: {current}

Activity in the last 7 days:
{activity}

Recent exercise scores:
{scores}

Produce a Markdown weekly review with these sections (in 中文):
## 这一周你实际学到了什么
## 薄弱点
## 下周建议
## 一个我注意到的模式
"""


STAGE_SYSTEM = """You are a senior learning coach producing a stage-level retrospective.
The learner has completed all nodes in a stage. Synthesize their journey:
- Major concepts they now own
- Common mistakes they overcame
- How well their understanding fits together (knowledge map)
- Readiness for the next stage

Style: Markdown, ≤900 words. Be opinionated.

LANGUAGE: write in 中文(Simplified Chinese). Keep technical terms in English.
Section headings should also be 中文.
"""


STAGE_USER_TPL = """Goal: {goal}

Stage just completed:
- ID: {sid}
- Name: {name}
- Nodes: {nodes}

Aggregate activity across this stage:
{activity}

Aggregate exercise scores:
{scores}

Produce sections (in 中文):
## 你已掌握的核心概念
## 你跨过的常见误区
## 知识地图(适合时使用 mermaid graph)
## 进入下一阶段的就绪度
## 下一阶段的第一步建议
"""


def _format_activity(entries) -> str:
    if not entries:
        return "(no activity)"
    out = []
    for e in entries:
        ts = e.ts[:10]
        if e.kind == "ask":
            out.append(f"- {ts} ❓ {e.content[:140]}")
        elif e.kind == "answer":
            out.append(f"- {ts} 💬 [tutor answer, {len(e.content)} chars]")
        elif e.kind == "test":
            out.append(f"- {ts} 🧪 {e.content[:140]}")
        elif e.kind == "fetch":
            out.append(f"- {ts} 📚 {e.content[:140]}")
        elif e.kind == "advance":
            out.append(f"- {ts} ➡️ {e.content[:140]}")
        elif e.kind == "study":
            out.append(f"- {ts} 📖 {e.content[:140]}")
    return "\n".join(out[-150:])


def _format_scores(sessions) -> str:
    if not sessions:
        return "(no exercises taken)"
    lines = []
    for s in sessions:
        date = s.started_at[:10]
        lines.append(f"- {date} · node {s.node_id} · overall {s.overall_score:.2f}"
                     if s.overall_score is not None else f"- {date} · node {s.node_id} · (incomplete)")
        for a in s.attempts:
            lines.append(f"    · {a.qid}: {a.score:.2f}")
    return "\n".join(lines)


def weekly_review(plan: LearningPlan) -> Path:
    """Generate a weekly review and save to library/notes/reviews/weekly_<date>.md."""
    cutoff = datetime.now() - timedelta(days=7)
    all_entries = load_trajectory(limit=10000)
    recent = [e for e in all_entries if e.ts >= cutoff.isoformat()]
    all_exes = load_exercises()
    recent_exes = [s for s in all_exes if s.started_at >= cutoff.isoformat()]

    cur = plan.find_node(plan.current_node_id) if plan.current_node_id else None
    cur_str = f"{cur.id} {cur.name}" if cur else "(none)"

    user = WEEKLY_USER_TPL.format(
        goal=plan.goal, current=cur_str,
        activity=_format_activity(recent),
        scores=_format_scores(recent_exes),
    )
    md = chat(
        WEEKLY_SYSTEM,
        user,
        model=REVIEWER_MODEL or None,
        max_tokens=2200,
        temperature=0.3,
    )

    reviews_dir = workspace_path("library", "notes", "reviews")
    reviews_dir.mkdir(parents=True, exist_ok=True)
    target = reviews_dir / f"weekly_{datetime.now().date().isoformat()}.md"
    target.write_text(md, encoding="utf-8")
    return target


def stage_review(plan: LearningPlan, stage_id: int) -> Path:
    """Generate a stage retrospective."""
    stage = next((s for s in plan.stages if s.id == stage_id), None)
    if not stage:
        raise ValueError(f"stage {stage_id} not found")

    node_ids = [n.id for n in stage.nodes]
    all_entries = load_trajectory(limit=10000)
    stage_entries = [e for e in all_entries if e.node_id in node_ids]
    all_exes = load_exercises()
    stage_exes = [s for s in all_exes if s.node_id in node_ids]

    user = STAGE_USER_TPL.format(
        goal=plan.goal,
        sid=stage.id, name=stage.name,
        nodes=", ".join(f"{n.id} {n.name}" for n in stage.nodes),
        activity=_format_activity(stage_entries),
        scores=_format_scores(stage_exes),
    )
    md = chat(
        STAGE_SYSTEM,
        user,
        model=REVIEWER_MODEL or None,
        max_tokens=3200,
        temperature=0.3,
    )

    reviews_dir = workspace_path("library", "notes", "reviews")
    reviews_dir.mkdir(parents=True, exist_ok=True)
    target = reviews_dir / f"stage_{stage_id}_{datetime.now().date().isoformat()}.md"
    target.write_text(md, encoding="utf-8")
    return target
