from __future__ import annotations

from rl_agent_tutor import config
from rl_agent_tutor.services import knowledge
from rl_agent_tutor.store import load_plan, load_trajectory


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


def test_apply_latest_weekly_review_adds_nodes(sample_plan):
    review_dir = config.workspace_path("library", "notes", "reviews")
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "weekly_2026-06-02.md").write_text(
        "## 下一步建议\n- 增加 PPO clip 的代码复现\n- 补做 GAE 推导\n",
        encoding="utf-8",
    )

    result = knowledge.apply_latest_weekly_review()

    assert result["applied"] == 2
    plan = load_plan()
    assert plan.stages[-1].name == "复盘调整"
    assert plan.stages[-1].nodes[0].name.startswith("增加 PPO")


def test_apply_latest_weekly_review_updates_existing_nodes(sample_plan):
    review_dir = config.workspace_path("library", "notes", "reviews")
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "weekly_2026-06-03.md").write_text(
        "\n".join(
            [
                "## 下一步建议",
                "- [estimate:0.1] 将 PPO clip 节点估时调整为 2-3h，并补充代码实验",
                "- [reorder:0.2] before 0.1，优先学习第二节点",
            ]
        ),
        encoding="utf-8",
    )

    result = knowledge.apply_latest_weekly_review()

    plan = load_plan()
    assert result["updated_nodes"] == ["0.1"]
    assert result["reordered_nodes"] == ["0.2"]
    assert plan.find_node("0.1").estimated_hours == (2.0, 3.0)
    assert plan.stage_of("0.2").nodes[0].id == "0.2"
    assert "代码实验" in plan.find_node("0.1").notes
