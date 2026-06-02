from __future__ import annotations

from fastapi.testclient import TestClient

from rl_agent_tutor.models import Resource
from rl_agent_tutor.routes import study
from rl_agent_tutor.server import app
from rl_agent_tutor.sources import source_config_path
from rl_agent_tutor.store import append_resource, load_resources


def test_new_learning_capabilities_flow(sample_plan, tmp_path, monkeypatch):
    """Regression for the post-refactor learning loop capabilities.

    This stays LLM/network-free while proving the new pieces compose:
    configurable sources -> recommendation workflow -> structured courseware ->
    evidence lifecycle -> mastery dashboard.
    """
    source_config = source_config_path()
    source_config.parent.mkdir(parents=True, exist_ok=True)
    source_config.write_text(
        """
defaults:
  enabled:
    - github
custom_sources:
  - id: local-notes
    type: local_directory
    name: Local Notes
    path: library/manual
    priority: core
""".strip(),
        encoding="utf-8",
    )

    client = TestClient(app)

    sources = client.get("/api/sources").json()["sources"]
    assert any(source["id"] == "local-notes" for source in sources)
    assert client.get("/api/plan").json()["recommended_action"]["id"] == "fetch_resources"

    note = tmp_path / "note.md"
    note.write_text("PPO clip ratio note", encoding="utf-8")
    append_resource(
        Resource(
            node_id="0.1",
            kind="blog",
            title="PPO note",
            local_path=str(note),
            source_id="local-notes",
            priority="core",
        )
    )
    assert client.get("/api/plan").json()["recommended_action"]["id"] == "generate_courseware"

    def fake_generate_courseware(node, stage_name=""):
        return {
            "node_id": node.id,
            "markdown": "# PPO 课件",
            "courseware": {
                "node_id": node.id,
                "title": "PPO 课件",
                "learning_objectives": ["解释 clip ratio"],
                "sections": [
                    {
                        "id": "overview",
                        "title": "概览",
                        "type": "concept",
                        "blocks": [
                            {
                                "type": "paragraph",
                                "title": "",
                                "content": {"text": "PPO 用 clip 控制更新幅度。"},
                            },
                            {
                                "type": "quiz",
                                "title": "检查点",
                                "content": {"questions": ["clip ratio 限制了什么?"]},
                            },
                        ],
                    }
                ],
                "key_takeaways": ["保守更新"],
                "references": [],
                "version": "structured-v1",
            },
            "path": str(tmp_path / "courseware.md"),
            "json_path": str(tmp_path / "courseware.json"),
            "sources_used": 1,
            "sources_total": 1,
        }

    monkeypatch.setattr(study.courseware, "load_courseware", lambda node: None)
    monkeypatch.setattr(study.courseware, "generate_courseware", fake_generate_courseware)

    courseware = client.post("/api/courseware").json()
    assert courseware["courseware"]["sections"][0]["blocks"][1]["type"] == "quiz"
    resource = load_resources("0.1")[0]
    assert resource.status == "read"
    assert resource.used_by[0].startswith("courseware:")
    assert client.get("/api/plan").json()["recommended_action"]["id"] == "start_test"

    submit = client.post(
        "/api/test/submit",
        json={
            "node_id": "0.1",
            "questions": [
                {
                    "qid": "q1",
                    "type": "concept",
                    "question": "clip?",
                    "expected_points": ["update bound"],
                }
            ],
            "attempts": [
                {
                    "qid": "q1",
                    "answer": "limits policy update",
                    "score": 0.9,
                    "feedback": "ok",
                }
            ],
        },
    )
    assert submit.status_code == 200
    assert client.get("/api/plan").json()["recommended_action"]["id"] == "advance"

    stats = client.get("/api/stats").json()["dashboard"]
    assert stats["mastery"]["solid_nodes"] == 1
    assert stats["resource_utilization"]["used"] == 1
    assert stats["recommended_action"]["id"] == "advance"

    advance = client.post("/api/advance", json={})
    assert advance.status_code == 200
    assert advance.json()["gate"]["passed"] is True
    assert advance.json()["next"] == "0.2"
