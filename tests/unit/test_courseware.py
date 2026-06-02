from __future__ import annotations

from pathlib import Path

from rl_agent_tutor import courseware
from rl_agent_tutor.courseware_export import export_courseware
from rl_agent_tutor.courseware_extractor import extract_media_blocks
from rl_agent_tutor.courseware_schema import (
    ContentBlock,
    Courseware,
    CoursewareSection,
    markdown_to_courseware,
    render_courseware_markdown,
)
from rl_agent_tutor.models import Resource
from rl_agent_tutor.store import append_resource


def test_render_courseware_markdown_handles_structured_blocks():
    cw = Courseware(
        node_id="0.1",
        title="PPO",
        learning_objectives=["解释 clip ratio"],
        sections=[
            CoursewareSection(
                id="overview",
                title="概览",
                blocks=[
                    ContentBlock(type="paragraph", content={"text": "核心解释"}),
                    ContentBlock(
                        type="table",
                        title="对比",
                        content={"headers": ["A", "B"], "rows": [["old", "new"]]},
                    ),
                    ContentBlock(
                        type="diagram",
                        title="流程",
                        content={"format": "mermaid", "code": "flowchart LR\nA-->B"},
                    ),
                ],
            )
        ],
        key_takeaways=["限制更新幅度"],
    )

    md = render_courseware_markdown(cw)

    assert "# PPO" in md
    assert "| A | B |" in md
    assert "```mermaid" in md
    assert "限制更新幅度" in md


def test_render_courseware_markdown_includes_video_segments():
    cw = Courseware(
        node_id="0.1",
        title="Video Lesson",
        sections=[
            CoursewareSection(
                id="video",
                title="视频学习",
                blocks=[
                    ContentBlock(
                        type="video",
                        title="PPO lecture",
                        content={
                            "url": "https://www.youtube.com/watch?v=abcdefghijk",
                            "summary": "看 clip objective 的解释。",
                            "segments": [
                                {
                                    "start_seconds": 200,
                                    "end_seconds": 360,
                                    "title": "Clip objective",
                                    "why_watch": "理解 ratio 被截断的原因",
                                    "checkpoint_question": "ratio 超出区间后梯度会怎样?",
                                }
                            ],
                        },
                    )
                ],
            )
        ],
    )

    md = render_courseware_markdown(cw)

    assert "3:20-6:00 Clip objective" in md
    assert "检查点: ratio 超出区间后梯度会怎样?" in md


def test_markdown_to_courseware_wraps_legacy_markdown():
    cw = markdown_to_courseware("0.1", "Legacy", "## 概览\ntext")

    assert cw.node_id == "0.1"
    assert cw.sections[0].blocks[0].content["markdown"].startswith("## 概览")


def test_generate_courseware_saves_structured_json(sample_plan, tmp_path, monkeypatch):
    source = tmp_path / "blog.md"
    source.write_text("PPO clip ratio material", encoding="utf-8")
    append_resource(
        Resource(
            node_id="0.1",
            kind="blog",
            title="Blog",
            local_path=str(source),
            source_id="website",
        )
    )
    monkeypatch.setattr(
        courseware,
        "chat_json",
        lambda system, user, max_tokens=4096, max_attempts=3: {
            "node_id": "0.1",
            "title": "PPO 课件",
            "learning_objectives": ["解释 PPO clip"],
            "sections": [
                {
                    "id": "overview",
                    "title": "概览",
                    "type": "concept",
                    "blocks": [
                        {"type": "paragraph", "content": {"text": "PPO 用 clip 控制更新幅度。"}},
                        {
                            "type": "quiz",
                            "title": "检查点",
                            "content": {"questions": ["clip ratio 限制了什么?"]},
                        },
                    ],
                }
            ],
            "key_takeaways": ["clip 是保守更新机制"],
            "references": [],
        },
    )

    result = courseware.generate_courseware(sample_plan.find_node("0.1"))

    assert result["courseware"]["title"] == "PPO 课件"
    assert result["sources_used"] == 1
    assert result["json_path"].endswith(".json")
    assert "clip 是保守更新机制" in result["markdown"]
    cached = courseware.load_courseware(sample_plan.find_node("0.1"))
    assert cached["courseware"]["title"] == "PPO 课件"


def test_generate_courseware_falls_back_to_markdown(sample_plan, monkeypatch):
    monkeypatch.setattr(courseware, "_build_materials_block", lambda node: ("material", []))

    def fail_json(*args, **kwargs):
        raise ValueError("bad json")

    monkeypatch.setattr(courseware, "chat_json", fail_json)
    monkeypatch.setattr(courseware, "chat", lambda *args, **kwargs: "## 概览\nfallback")

    result = courseware.generate_courseware(sample_plan.find_node("0.1"))

    assert result["courseware"]["sections"][0]["id"] == "markdown"
    assert "fallback" in result["markdown"]


def test_extract_media_blocks_from_markdown_image(sample_plan, tmp_path):
    image = tmp_path / "diagram.png"
    image.write_bytes(b"fake")
    note = tmp_path / "note.md"
    note.write_text("![机制图](diagram.png)", encoding="utf-8")
    resource = Resource(node_id="0.1", kind="note", title="Note", local_path=str(note))

    blocks = extract_media_blocks(sample_plan.find_node("0.1"), [resource])

    assert blocks[0].type == "image"
    assert blocks[0].content["local_path"].endswith("diagram.png")


def test_extract_media_blocks_from_html_figure(sample_plan, tmp_path):
    html = tmp_path / "article.html"
    html.write_text(
        '<html><body><article><figure><img data-src="https://example.com/fig.png"></figure></article></body></html>',
        encoding="utf-8",
    )
    resource = Resource(node_id="0.1", kind="blog", title="Article", local_path=str(html))

    blocks = extract_media_blocks(sample_plan.find_node("0.1"), [resource])

    assert blocks[0].content["local_path"] == "https://example.com/fig.png"


def test_regenerate_section_replaces_only_target_section(sample_plan, tmp_path, monkeypatch):
    source = tmp_path / "blog.md"
    source.write_text("PPO material", encoding="utf-8")
    append_resource(Resource(node_id="0.1", kind="blog", title="Blog", local_path=str(source)))
    original = Courseware(
        node_id="0.1",
        title="PPO",
        sections=[
            CoursewareSection(id="overview", title="旧概览", blocks=[]),
            CoursewareSection(id="quiz", title="自测", blocks=[]),
        ],
    )
    courseware._save_courseware(sample_plan.find_node("0.1"), original, [])
    monkeypatch.setattr(
        courseware,
        "chat_json",
        lambda *args, **kwargs: {
            "id": "overview",
            "title": "新概览",
            "type": "concept",
            "blocks": [{"type": "paragraph", "content": {"text": "updated"}}],
        },
    )

    result = courseware.regenerate_section(sample_plan.find_node("0.1"), "overview")

    sections = result["courseware"]["sections"]
    assert sections[0]["title"] == "新概览"
    assert sections[1]["title"] == "自测"


def test_export_courseware_writes_markdown_html_pdf(workspace):
    cw = Courseware(
        node_id="0.1",
        title="PPO",
        sections=[CoursewareSection(id="overview", title="概览", blocks=[ContentBlock(type="paragraph", content={"text": "text"})])],
    )

    result = export_courseware(cw)

    assert set(result["files"]) == {"markdown", "html", "pdf"}
    for path in result["files"].values():
        assert Path(path).exists()
