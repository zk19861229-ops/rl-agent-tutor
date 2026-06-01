from __future__ import annotations

from rl_agent_tutor import config
from rl_agent_tutor.services import knowledge
from rl_agent_tutor.store import load_trajectory


def test_archive_writes_index_and_records_review(sample_plan, monkeypatch):
    def fake_archive_node(node, stage_name="", use_rag=True):
        target = config.workspace_path("library", "notes", f"{node.id}_first.md")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# node", encoding="utf-8")
        return target

    def fake_build_index(plan):
        target = config.workspace_path("library", "notes", "INDEX.md")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# index", encoding="utf-8")
        return target

    monkeypatch.setattr(knowledge.archivist, "archive_node", fake_archive_node)
    monkeypatch.setattr(knowledge.archivist, "build_index", fake_build_index)

    result = knowledge.archive()

    assert result.index_file.name == "INDEX.md"
    assert knowledge.read_kb_index() == "# index"
    assert knowledge.read_kb_node("0.1") == "# node"
    assert load_trajectory(limit=1)[0].kind == "review"
