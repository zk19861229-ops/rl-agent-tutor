"""Archivist Agent — distill trajectory + exercises + resources into a per-node knowledge base.

For each node, produces a Markdown file at workspace/library/notes/<node_id>_<slug>.md
containing: core concepts (synthesized), Q&A highlights, mistakes & corrections,
resource index, and an open-questions list.
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime
from .llm import chat
from .models import LearningNode, TrajectoryEntry, ExerciseSession, Resource
from .store import (
    load_trajectory, load_exercises, load_resources,
)
from .config import workspace_path
from .utils import slugify
from . import rag


ARCHIVIST_SYSTEM = """You are a meticulous knowledge curator for an RL/LLM learner.
Given raw trajectory data (questions asked, answers given, exercise attempts, resources fetched)
for one learning node, you distill them into a clean, well-organized Markdown knowledge base entry.

Hard rules:
- Be a CURATOR, not a TEACHER. Reorganize and synthesize what's already there; don't add new content from your own knowledge unless explicitly asked.
- Drop fluff. If two Q&A items cover the same point, merge them. If an answer was wrong, capture both the wrong intuition and the correction.
- Mistake patterns are gold — explicitly highlight them.
- Output PURE Markdown, ready to paste into a wiki. No "here is the knowledge base:" preamble.

LANGUAGE: write the KB entry in 中文(Simplified Chinese). Keep technical terms,
library names, paper titles, and code identifiers in English (e.g. "PPO", "DPO",
"advantage", "TRL"). Original quotes from English sources may stay English when verbatim.
"""


ARCHIVIST_USER_TEMPLATE = """# Source: Node {nid} — {name}

Description: {desc}
Stage: {stage}
Objectives:
{objs}

## Resources fetched
{resources_block}

## Trajectory (Q&A and study events, oldest → newest)
{trajectory_block}

## Exercise sessions
{exercises_block}

---

Produce a Markdown knowledge base entry with this exact structure:

# Node {nid} · {name}

> One-paragraph summary of what this node is about and why it matters (synthesize from the material above).

## Core concepts
(Bulleted list of the 4–8 distinct concepts that came up. For each: **Concept** — 1–2 sentence essence, drawing from the actual Q&A in the trajectory.)

## Q&A highlights
(3–6 most useful Q&A pairs, each formatted as:)
**Q:** ...
**A:** ... (the key insight, condensed; not the full answer)

## Mistakes & corrections
(For each wrong/partial answer in exercises or any "I thought X but actually Y" pattern in trajectory:)
- **❌ Misconception:** ...
- **✅ Correction:** ...
- **Why this matters:** ...

(If no mistakes, write "No documented mistakes yet.")

## Resources
(Tabulate paper / code / blog / video resources with local paths or URLs.)

## Open questions
(List anything still unresolved — questions asked but not satisfactorily answered, or topics flagged for follow-up.)

## Updated
{ts}
"""


def _slugify(s: str) -> str:
    return slugify(s, n=60, lower=True)


def _format_resources(rs: list[Resource]) -> str:
    if not rs:
        return "(none yet)"
    lines = []
    for r in rs:
        loc = r.local_path or r.url or "—"
        lines.append(f"- [{r.kind}] **{r.title}** — `{loc}`")
        if r.summary:
            lines.append(f"  - {r.summary[:200].strip()}")
    return "\n".join(lines)


def _format_trajectory(entries: list[TrajectoryEntry]) -> str:
    if not entries:
        return "(no entries)"
    out = []
    for e in entries:
        ts = e.ts[:19].replace("T", " ")
        if e.kind == "ask":
            out.append(f"[{ts}] Q: {e.content}")
        elif e.kind == "answer":
            out.append(f"[{ts}] A: {e.content}")
        elif e.kind in ("study", "fetch", "test", "advance"):
            out.append(f"[{ts}] {e.kind}: {e.content}")
    return "\n\n".join(out) if out else "(no relevant entries)"


def _format_exercises(sessions: list[ExerciseSession]) -> str:
    if not sessions:
        return "(no exercises taken)"
    out = []
    for sess in sessions:
        out.append(f"### Session @ {sess.started_at[:19]} (overall: {sess.overall_score})")
        for i, q in enumerate(sess.questions):
            attempt = next((a for a in sess.attempts if a.qid == q.qid), None)
            out.append(f"**Q{i+1} ({q.type}):** {q.question}")
            out.append(f"- Expected points: {', '.join(q.expected_points) or '(none)'}")
            if attempt:
                out.append(f"- Learner answered: {attempt.answer[:300] or '(empty)'}")
                out.append(f"- Score: {attempt.score:.2f}")
                out.append(f"- Feedback: {attempt.feedback[:400]}")
            else:
                out.append("- (not attempted)")
            out.append("")
    return "\n".join(out)


def archive_node(node: LearningNode, stage_name: str = "", use_rag: bool = True) -> Path:
    """Produce/refresh the knowledge base file for a single node."""
    trajectory = load_trajectory(node_id=node.id, limit=1000)
    exercises = load_exercises(node_id=node.id)
    resources = load_resources(node_id=node.id)

    rag_block = ""
    if use_rag:
        query = f"{node.name}. {node.description}. " + " ".join(node.objectives)
        ctx, _, _ = rag.with_rag(query, top_n=4, max_chars=6000)
        if ctx:
            rag_block = "\n## Library excerpts (cite these in the KB when relevant)\n" + ctx

    user = ARCHIVIST_USER_TEMPLATE.format(
        nid=node.id, name=node.name, desc=node.description,
        stage=stage_name or "(unknown)",
        objs="\n".join(f"- {o}" for o in node.objectives) or "- (none)",
        resources_block=_format_resources(resources),
        trajectory_block=_format_trajectory(trajectory),
        exercises_block=_format_exercises(exercises),
        ts=datetime.now().isoformat(timespec="seconds"),
    ) + rag_block

    md = chat(ARCHIVIST_SYSTEM, user, max_tokens=6000, temperature=0.2)

    notes_dir = workspace_path("library", "notes")
    notes_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{node.id}_{_slugify(node.name)}.md"
    target = notes_dir / fname
    # If the node was renamed since the last archive, the old slug-based file
    # would otherwise stay around as an orphan. Sweep stale `<node.id>_*.md`
    # entries other than the current target so the KB stays coherent.
    for stale in notes_dir.glob(f"{node.id}_*.md"):
        if stale.name != fname and stale.is_file():
            try:
                stale.unlink()
            except OSError:
                pass
    target.write_text(md, encoding="utf-8")
    return target


def archive_all(plan, only_completed: bool = False) -> list[Path]:
    """Archive every node (or only completed ones)."""
    results: list[Path] = []
    for s in plan.stages:
        for n in s.nodes:
            if only_completed and n.status != "completed":
                continue
            # skip nodes with zero activity
            if not (load_trajectory(node_id=n.id, limit=1) or
                    load_exercises(node_id=n.id) or
                    load_resources(node_id=n.id)):
                continue
            results.append(archive_node(n, stage_name=s.name))
    return results


KB_INDEX_SYSTEM = """You build a top-level INDEX file for a personal knowledge base.
You receive a list of per-node knowledge files and must produce a Markdown index that
groups them by stage, gives a one-line description for each, and highlights the most
recent activity. Be concise."""


def build_index(plan) -> Path:
    """Produce a top-level KB index across all archived nodes."""
    notes_dir = workspace_path("library", "notes")
    notes_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(notes_dir.glob("*.md"))
    files = [f for f in files if f.name != "INDEX.md"]

    lines = [f"# Knowledge Base — {plan.goal}", ""]
    lines.append(f"_Generated {datetime.now().isoformat(timespec='seconds')}_")
    lines.append(f"_LLM-curated synthesis. Source data lives in `progress/`._")
    lines.append("")
    for s in plan.stages:
        stage_files = []
        for n in s.nodes:
            slug = f"{n.id}_{_slugify(n.name)}.md"
            target = notes_dir / slug
            if target.exists():
                stage_files.append((n, target))
        if not stage_files:
            continue
        lines.append(f"## Stage {s.id} · {s.name}")
        lines.append("")
        for n, path in stage_files:
            status_icon = {"completed": "✅", "in_progress": "🔄", "self_testing": "🧪",
                           "pending": "⬜"}.get(n.status, "•")
            lines.append(f"- {status_icon} **[{n.id} {n.name}](./{path.name})** — {n.description}")
        lines.append("")

    target = notes_dir / "INDEX.md"
    target.write_text("\n".join(lines), encoding="utf-8")
    return target
