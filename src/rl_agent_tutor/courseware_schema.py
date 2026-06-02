"""Structured courseware models and renderers."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


BlockType = Literal[
    "paragraph",
    "callout",
    "formula",
    "code",
    "table",
    "diagram",
    "image",
    "video",
    "quiz",
    "reference",
]


class ContentBlock(BaseModel):
    type: BlockType
    title: str = ""
    content: dict = Field(default_factory=dict)


class CoursewareSection(BaseModel):
    id: str
    title: str
    type: Literal["concept", "mechanism", "math", "code", "case_study", "comparison", "summary"] = "concept"
    blocks: list[ContentBlock] = Field(default_factory=list)


class CoursewareReference(BaseModel):
    title: str
    source_id: str = ""
    url: str | None = None
    local_path: str | None = None


class Courseware(BaseModel):
    node_id: str
    title: str
    learning_objectives: list[str] = Field(default_factory=list)
    sections: list[CoursewareSection] = Field(default_factory=list)
    key_takeaways: list[str] = Field(default_factory=list)
    references: list[CoursewareReference] = Field(default_factory=list)
    version: str = "structured-v1"


def markdown_to_courseware(node_id: str, title: str, markdown: str) -> Courseware:
    return Courseware(
        node_id=node_id,
        title=title,
        sections=[
            CoursewareSection(
                id="markdown",
                title="学习课件",
                type="summary",
                blocks=[
                    ContentBlock(
                        type="paragraph",
                        content={"markdown": markdown},
                    )
                ],
            )
        ],
    )


def render_courseware_markdown(courseware: Courseware) -> str:
    parts: list[str] = [f"# {courseware.title}".strip()]
    if courseware.learning_objectives:
        parts.append("## 学习目标\n" + "\n".join(f"- {item}" for item in courseware.learning_objectives))
    for section in courseware.sections:
        parts.append(f"## {section.title}")
        for block in section.blocks:
            rendered = _render_block(block)
            if rendered:
                parts.append(rendered)
    if courseware.key_takeaways:
        parts.append("## 关键结论\n" + "\n".join(f"- {item}" for item in courseware.key_takeaways))
    if courseware.references:
        refs = []
        for ref in courseware.references:
            suffix = ref.url or ref.local_path or ref.source_id
            refs.append(f"- {ref.title}" + (f" — {suffix}" if suffix else ""))
        parts.append("## 参考资料\n" + "\n".join(refs))
    return "\n\n".join(parts).strip()


def _render_block(block: ContentBlock) -> str:
    content = block.content or {}
    title = f"### {block.title}\n" if block.title else ""
    if block.type == "paragraph":
        return title + str(content.get("markdown") or content.get("text") or "").strip()
    if block.type == "callout":
        text = str(content.get("text") or "").strip()
        return title + (f"> {text}" if text else "")
    if block.type == "formula":
        formula = str(content.get("formula") or "").strip()
        caption = str(content.get("caption") or "").strip()
        return title + "\n".join(part for part in (f"$${formula}$$" if formula else "", caption) if part)
    if block.type == "code":
        language = str(content.get("language") or "text")
        code = str(content.get("code") or "").strip()
        caption = str(content.get("caption") or "").strip()
        body = f"```{language}\n{code}\n```" if code else ""
        return title + "\n".join(part for part in (body, caption) if part)
    if block.type == "table":
        headers = content.get("headers") or []
        rows = content.get("rows") or []
        if not headers or not rows:
            return title
        table = [
            "| " + " | ".join(str(h) for h in headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ]
        for row in rows:
            table.append("| " + " | ".join(str(cell) for cell in row) + " |")
        return title + "\n".join(table)
    if block.type == "diagram":
        code = str(content.get("code") or "").strip()
        fmt = str(content.get("format") or "mermaid")
        return title + (f"```{fmt}\n{code}\n```" if code else "")
    if block.type == "video":
        url = str(content.get("url") or "").strip()
        summary = str(content.get("summary") or "").strip()
        segments = content.get("segments") or content.get("key_segments") or []
        segment_lines = []
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            label = _segment_label(seg)
            why = str(seg.get("why_watch") or seg.get("summary") or "").strip()
            question = str(seg.get("checkpoint_question") or "").strip()
            line = f"- {label}" + (f" — {why}" if why else "")
            if question:
                line += f"\n  - 检查点: {question}"
            segment_lines.append(line)
        return title + "\n".join(
            part for part in (
                url,
                summary,
                "建议片段:\n" + "\n".join(segment_lines) if segment_lines else "",
            )
            if part
        )
    if block.type == "quiz":
        questions = content.get("questions") or []
        return title + "\n".join(f"- {q}" for q in questions)
    if block.type == "reference":
        return title + str(content.get("text") or content.get("url") or "").strip()
    if block.type == "image":
        url = str(content.get("url") or content.get("local_path") or "").strip()
        alt = str(content.get("alt") or block.title or "image")
        caption = str(content.get("caption") or "").strip()
        return title + "\n".join(part for part in (f"![{alt}]({url})" if url else "", caption) if part)
    return ""


def _segment_label(seg: dict) -> str:
    title = str(seg.get("title") or "片段").strip()
    start = seg.get("start_seconds")
    end = seg.get("end_seconds")
    if isinstance(start, int) and isinstance(end, int):
        return f"{_fmt_time(start)}-{_fmt_time(end)} {title}"
    if isinstance(start, int):
        return f"{_fmt_time(start)} {title}"
    return title


def _fmt_time(seconds: int) -> str:
    minutes, sec = divmod(max(0, seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes}:{sec:02d}"
