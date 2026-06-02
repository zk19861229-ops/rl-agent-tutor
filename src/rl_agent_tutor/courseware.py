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

from .courseware_schema import (
    Courseware,
    CoursewareReference,
    CoursewareSection,
    markdown_to_courseware,
    render_courseware_markdown,
)
from .courseware_extractor import build_materials_block, extract_media_blocks
from .courseware_generator import attach_media_blocks
from .courseware_renderer import render_markdown
from .llm import chat, chat_json
from .models import LearningNode, Resource
from .store import load_resources
from .config import workspace_path
from .utils import slugify


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
    return slugify(s, n=n, lower=True) or "node"


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

STRUCTURED_COURSEWARE_SYSTEM = """You create structured courseware JSON for a technical learner.
Return compact valid JSON only. The content must teach, not merely summarize.

LANGUAGE: write Chinese text. Keep technical terms, code identifiers, paper titles,
library names, and formulas in English when appropriate.

Use varied block types when useful:
- paragraph for concise explanation
- callout for key warnings or misconceptions
- formula for math
- code for minimal runnable snippets
- table for comparisons
- diagram with Mermaid code for mechanisms or workflows
- video for YouTube resources with suggested segments
- quiz for checkpoint questions
"""

STRUCTURED_COURSEWARE_USER_TPL = """Learning node:
- ID: {nid}
- Stage: {stage}
- Name: {name}
- Description: {desc}
- Objectives: {objs}

Source materials:
{materials}

Return EXACTLY this JSON shape:
{{
  "node_id": "{nid}",
  "title": "...",
  "learning_objectives": ["...", "..."],
  "sections": [
    {{
      "id": "overview",
      "title": "本节要解决的问题",
      "type": "concept",
      "blocks": [
        {{"type": "paragraph", "title": "", "content": {{"text": "..."}}}},
        {{"type": "diagram", "title": "机制图", "content": {{"format": "mermaid", "code": "flowchart LR\\nA-->B", "caption": "..."}}}},
        {{"type": "video", "title": "视频片段", "content": {{"url": "https://www.youtube.com/watch?v=...", "summary": "...", "segments": [
          {{"start_seconds": 120, "end_seconds": 360, "title": "...", "why_watch": "...", "checkpoint_question": "..."}}
        ]}}}},
        {{"type": "quiz", "title": "检查点", "content": {{"questions": ["..."]}}}}
      ]
    }}
  ],
  "key_takeaways": ["...", "..."],
  "references": [
    {{"title": "...", "source_id": "...", "url": null, "local_path": null}}
  ]
}}

Rules:
- 4 to 7 sections.
- Include at least one table OR diagram when the topic has relationships or workflow.
- Include at least one quiz block.
- If a source is video/transcript, include a video block with url, summary, and 1-3 segments when possible.
- Mermaid diagrams should use simple flowchart/state/sequence syntax and include a caption.
- Keep total content under 1800 Chinese characters.
JSON only."""

SECTION_REGEN_SYSTEM = """You regenerate one section of structured technical courseware.
Return valid compact JSON for a single CoursewareSection only. Keep Chinese text concise,
use varied blocks, and preserve the requested section id.
"""

SECTION_REGEN_USER_TPL = """Learning node:
- ID: {nid}
- Stage: {stage}
- Name: {name}
- Description: {desc}
- Objectives: {objs}

Regenerate this section:
- section_id: {section_id}
- title: {title}
- type: {section_type}

Source materials:
{materials}

Return exactly:
{{
  "id": "{section_id}",
  "title": "...",
  "type": "{section_type}",
  "blocks": [
    {{"type": "paragraph", "title": "", "content": {{"text": "..."}}}},
    {{"type": "quiz", "title": "检查点", "content": {{"questions": ["..."]}}}}
  ]
}}
JSON only."""


def _build_materials_block(node: LearningNode) -> tuple[str, list[Resource]]:
    """Collect extracts from all usable resources. Returns (block_text, used_resources)."""
    return build_materials_block(node)


def _legacy_build_materials_block(node: LearningNode) -> tuple[str, list[Resource]]:
    """Previous inline extractor kept for compatibility with tests/imports."""
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

    courseware = _generate_structured_courseware(node, stage_name, materials, used)
    if courseware is None:
        md = _generate_markdown_courseware(node, stage_name, materials)
        courseware = markdown_to_courseware(node.id, node.name, md)
    else:
        courseware = attach_media_blocks(courseware, extract_media_blocks(node, used))
        md = render_markdown(courseware)

    out_dir = workspace_path("library", "notes", "courseware")
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{node.id}_{_slugify(node.name)}"
    md_target = out_dir / f"{stem}.md"
    json_target = out_dir / f"{stem}.json"

    header = (
        f"<!-- courseware for node {node.id} {node.name} -->\n"
        f"<!-- generated {datetime.now().isoformat(timespec='seconds')} -->\n"
        f"<!-- sources used: {len(used)} -->\n\n"
    )
    md_target.write_text(header + md, encoding="utf-8")
    json_target.write_text(courseware.model_dump_json(indent=2), encoding="utf-8")

    return {
        "node_id": node.id,
        "markdown": md,
        "courseware": courseware.model_dump(),
        "path": str(md_target),
        "json_path": str(json_target),
        "sources_used": len(used),
        "sources_total": len(load_resources(node_id=node.id)),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def regenerate_section(node: LearningNode, section_id: str, stage_name: str = "") -> dict:
    cached = load_courseware(node)
    if not cached or not cached.get("courseware"):
        raise ValueError("courseware not found")
    courseware = Courseware.model_validate(cached["courseware"])
    index = next((i for i, section in enumerate(courseware.sections) if section.id == section_id), -1)
    if index < 0:
        raise ValueError(f"section {section_id} not found")
    old = courseware.sections[index]
    materials, used = _build_materials_block(node)
    user = SECTION_REGEN_USER_TPL.format(
        nid=node.id,
        stage=stage_name or "(unknown)",
        name=node.name,
        desc=node.description,
        objs=", ".join(node.objectives) or "(none)",
        section_id=old.id,
        title=old.title,
        section_type=old.type,
        materials=materials,
    )
    raw = chat_json(SECTION_REGEN_SYSTEM, user, max_tokens=2200)
    new_section = CoursewareSection.model_validate(raw)
    courseware.sections[index] = new_section
    return _save_courseware(node, courseware, used)


def _save_courseware(node: LearningNode, courseware: Courseware, used: list[Resource] | None = None) -> dict:
    used = used or []
    md = render_markdown(courseware)
    out_dir = workspace_path("library", "notes", "courseware")
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{node.id}_{_slugify(node.name)}"
    md_target = out_dir / f"{stem}.md"
    json_target = out_dir / f"{stem}.json"
    header = (
        f"<!-- courseware for node {node.id} {node.name} -->\n"
        f"<!-- generated {datetime.now().isoformat(timespec='seconds')} -->\n"
        f"<!-- sources used: {len(used)} -->\n\n"
    )
    md_target.write_text(header + md, encoding="utf-8")
    json_target.write_text(courseware.model_dump_json(indent=2), encoding="utf-8")
    return {
        "node_id": node.id,
        "markdown": md,
        "courseware": courseware.model_dump(),
        "path": str(md_target),
        "json_path": str(json_target),
        "sources_used": len(used),
        "sources_total": len(load_resources(node_id=node.id)),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def _generate_markdown_courseware(node: LearningNode, stage_name: str, materials: str) -> str:
    user = COURSEWARE_USER_TPL.format(
        nid=node.id, stage=stage_name or "(unknown)",
        name=node.name, desc=node.description,
        objs=", ".join(node.objectives) or "(none)",
        materials=materials,
    )
    return chat(COURSEWARE_SYSTEM, user, max_tokens=4000, temperature=0.3)


def _generate_structured_courseware(
    node: LearningNode,
    stage_name: str,
    materials: str,
    used: list[Resource],
) -> Courseware | None:
    user = STRUCTURED_COURSEWARE_USER_TPL.format(
        nid=node.id,
        stage=stage_name or "(unknown)",
        name=node.name,
        desc=node.description,
        objs=", ".join(node.objectives) or "(none)",
        materials=materials,
    )
    try:
        raw = chat_json(
            STRUCTURED_COURSEWARE_SYSTEM,
            user,
            max_tokens=4500,
        )
        courseware = Courseware.model_validate(raw)
    except Exception:
        return None

    if not courseware.references and used:
        courseware.references.extend(
            CoursewareReference(
                title=r.title,
                source_id=r.source_id or r.kind,
                url=r.url,
                local_path=r.local_path,
            )
            for r in used[:8]
        )
    return courseware


def load_courseware(node: LearningNode) -> Optional[dict]:
    """Return the cached courseware for a node, or None."""
    stem = f"{node.id}_{_slugify(node.name)}"
    md_target = workspace_path("library", "notes", "courseware", f"{stem}.md")
    json_target = workspace_path("library", "notes", "courseware", f"{stem}.json")
    if not md_target.exists() and not json_target.exists():
        return None
    courseware = None
    if json_target.exists():
        try:
            courseware = Courseware.model_validate_json(json_target.read_text(encoding="utf-8"))
        except Exception:
            courseware = None
    if md_target.exists():
        text = md_target.read_text(encoding="utf-8")
        body = re.sub(r"^(?:<!--[^>]*-->\s*)+", "", text)
    elif courseware is not None:
        body = render_courseware_markdown(courseware)
    else:
        return None
    return {
        "node_id": node.id,
        "markdown": body,
        "courseware": courseware.model_dump() if courseware else None,
        "path": str(md_target),
        "json_path": str(json_target) if json_target.exists() else None,
        "cached": True,
    }
