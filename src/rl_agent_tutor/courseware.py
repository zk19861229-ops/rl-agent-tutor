"""Courseware Agent — synthesize fetched resources into a structured study sheet.

Pipeline for one node:
1) Load all successfully-fetched resources for the node (skip failures).
2) For each resource, extract readable content:
   - paper PDF       → first N pages of plain text via pymupdf (or skip if absent)
   - blog markdown   → read the saved .md
   - video transcript→ read the saved .md
   - code repo       → read README.md if present
3) Bundle everything into a single context, ask LLM to produce a 5-section
   markdown courseware (overview / core concepts / formulas-or-code / learning path / self-check).
4) Save to library/notes/courseware/<node_id>_<slug>.md and return.

The Agent is opinionated: it prefers tight prose, callouts, and concrete
examples over generic platitudes.
"""
from __future__ import annotations
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from .llm import chat
from .models import LearningNode, Resource
from .store import load_resources
from .config import workspace_path


_MAX_PER_RESOURCE = 4000   # chars of content per resource fed to the LLM
_MAX_PAPER_PAGES = 6       # only read first N pages of a paper PDF
_MAX_TOTAL_CTX = 28000     # safety cap on combined context size


# ---------- content extraction ----------

def _is_failed(r: Resource) -> bool:
    title = (r.title or "").lower()
    summary = (r.summary or "").lower()
    if title.startswith("[search failed"):
        return True
    if any(w in summary for w in ("download failed", "clone failed",
                                  "fetch failed", "transcript unavailable",
                                  "empty content extracted")):
        return True
    return False


def _read_pdf_text(path: Path, max_pages: int = _MAX_PAPER_PAGES) -> str:
    try:
        import fitz  # pymupdf
    except ImportError:
        return ""
    try:
        with fitz.open(path) as doc:
            pages = []
            for i, page in enumerate(doc):
                if i >= max_pages:
                    break
                try:
                    pages.append(page.get_text("text"))
                except Exception:
                    pass
        return "\n".join(pages).strip()
    except Exception:
        return ""


def _read_repo_readme(path: Path) -> str:
    """Look for README.md / README.rst / README at the repo root."""
    if not path.exists() or not path.is_dir():
        return ""
    for name in ("README.md", "README.MD", "README.rst", "README.txt", "README"):
        f = path / name
        if f.exists() and f.is_file():
            try:
                return f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
    return ""


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _extract(r: Resource) -> Optional[str]:
    """Return readable text excerpt for a resource, or None if nothing usable."""
    if _is_failed(r):
        return None
    lp = r.local_path
    if not lp:
        return None
    p = Path(lp)
    if not p.exists():
        return None
    if r.kind == "paper" and p.suffix.lower() == ".pdf":
        return _read_pdf_text(p)
    if r.kind in ("blog", "video"):
        return _read_text_file(p)
    if r.kind == "code":
        return _read_repo_readme(p)
    return None


def _slugify(s: str, n: int = 60) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", s).strip("_")
    return s[:n].lower() or "node"


# ---------- LLM synthesis ----------

COURSEWARE_SYSTEM = """You are a senior teacher who turns raw research material
into a tight, useful study sheet for a learner working on ONE specific learning node.

Audience: a learner with general technical background but new to this specific topic.
Goal: ≤ 1500 words of MARKDOWN that the learner can study in 15 minutes and
walk away knowing what matters.

Hard rules:
- Be a TEACHER, not a SUMMARIZER. Synthesize, simplify, cut filler.
- Cite the source briefly when drawing a specific claim, e.g. "(来自 paper:1707.06347)".
- Prefer concrete examples / numbers / minimal code over abstract definitions.
- Do NOT include resource lists or links — the learner already has the resource panel.

LANGUAGE: write the courseware in 中文(Simplified Chinese), even when the source materials
are entirely in English. Keep technical terms, library names, paper titles, code identifiers
in English (e.g. "PPO", "GAE", "advantage", "torch.nn.functional"). Math formulas may use
LaTeX. Section headings should be 中文.
"""

COURSEWARE_USER_TPL = """## Learning node
- ID: {nid}
- Stage: {stage}
- Name: {name}
- Description: {desc}
- Objectives: {objs}

## Source materials
{materials}

---

Produce a Markdown study sheet with EXACTLY these 5 H2 sections:

## 概览
3–5 sentences on what this node is about, why it matters, and how the pieces fit together.

## 核心概念
4–7 bullet points. Each: **概念名** — 1–2 sentence essence + (when useful) a tiny example or analogy.

## 重点公式 / 代码
The 1–3 formulas or minimal code snippets a learner MUST know.
Use ```python``` fenced blocks for code, $...$ or $$...$$ for math.
For each, add a one-line "为什么重要" caption.

## 推荐学习路径
A short ordered list (3–6 steps) of how to actually study this node, leveraging the
material above. Be specific: "先看 X 的第 N 节,再做 Y".

## 自检问题
4–6 questions that probe real understanding (not trivia). The learner should pause
and answer each before moving on.

Output the markdown only. No preface, no closing remarks.
"""


def _build_materials_block(node: LearningNode) -> tuple[str, list[Resource]]:
    """Collect extracts from all usable resources. Returns (block_text, used_resources)."""
    resources = load_resources(node_id=node.id)
    used: list[Resource] = []
    parts: list[str] = []
    total = 0
    for r in resources:
        excerpt = _extract(r)
        if not excerpt:
            continue
        excerpt = excerpt.strip()
        if not excerpt:
            continue
        excerpt = excerpt[:_MAX_PER_RESOURCE]
        if total + len(excerpt) > _MAX_TOTAL_CTX and parts:
            break
        # tag with kind + a short id derived from title or url
        tag = r.kind
        ident = r.title[:60] if r.title else (r.url or r.local_path or "")[:60]
        parts.append(f"### {tag}: {ident}\n{excerpt}\n")
        used.append(r)
        total += len(excerpt)
    if not parts:
        return "(no usable source material — fetch resources first or sources had no content)", []
    return "\n\n".join(parts), used


def generate_courseware(node: LearningNode, stage_name: str = "") -> dict:
    """Build courseware for a node. Saves to disk and returns dict with markdown + meta."""
    materials, used = _build_materials_block(node)

    user = COURSEWARE_USER_TPL.format(
        nid=node.id, stage=stage_name or "(unknown)",
        name=node.name, desc=node.description,
        objs=", ".join(node.objectives) or "(none)",
        materials=materials,
    )

    md = chat(COURSEWARE_SYSTEM, user, max_tokens=4000, temperature=0.3)

    out_dir = workspace_path("library", "notes", "courseware")
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{node.id}_{_slugify(node.name)}.md"
    target = out_dir / fname

    header = (
        f"<!-- courseware for node {node.id} {node.name} -->\n"
        f"<!-- generated {datetime.now().isoformat(timespec='seconds')} -->\n"
        f"<!-- sources used: {len(used)} -->\n\n"
    )
    target.write_text(header + md, encoding="utf-8")

    return {
        "node_id": node.id,
        "markdown": md,
        "path": str(target),
        "sources_used": len(used),
        "sources_total": len(load_resources(node_id=node.id)),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def load_courseware(node: LearningNode) -> Optional[dict]:
    """Return the cached courseware for a node, or None."""
    target = workspace_path("library", "notes", "courseware",
                            f"{node.id}_{_slugify(node.name)}.md")
    if not target.exists():
        return None
    text = target.read_text(encoding="utf-8")
    # strip our HTML comment header
    body = re.sub(r"^(?:<!--[^>]*-->\s*)+", "", text)
    return {
        "node_id": node.id,
        "markdown": body,
        "path": str(target),
        "cached": True,
    }
