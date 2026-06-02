from __future__ import annotations

import httpx
from anthropic import PermissionDeniedError
from fastapi.testclient import TestClient

from rl_agent_tutor.models import ExerciseAttempt, ExerciseQuestion, Resource
from rl_agent_tutor.server import app, create_app
from rl_agent_tutor.services import learning
from rl_agent_tutor.services import knowledge, resources
from rl_agent_tutor.routes import study, testing


def test_core_routes_smoke(sample_plan, monkeypatch):
    monkeypatch.setattr(
        resources.librarian,
        "fetch_for_node",
        lambda node, registry=None: [Resource(node_id=node.id, kind="blog", title="Blog")],
    )
    monkeypatch.setattr(study.practice, "best_practices", lambda node: "practice")
    monkeypatch.setattr(
        testing.examiner,
        "generate_exercises",
        lambda node: [ExerciseQuestion(qid="q1", type="concept", question="q")],
    )
    monkeypatch.setattr(
        testing.examiner,
        "grade_answer",
        lambda question, answer: ExerciseAttempt(
            qid=question.qid, answer=answer, score=1.0, feedback="ok"
        ),
    )

    client = TestClient(app)

    assert client.get("/").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/plan").json()["plan"]["goal"] == "goal"
    assert client.post("/api/goto", json={"node_id": "0.1"}).status_code == 200
    assert client.post("/api/fetch").json()["resources"][0]["title"] == "Blog"
    assert client.post("/api/practices").json()["text"] == "practice"
    assert client.post("/api/test/start", json={"node_id": "0.1"}).status_code == 200
    assert (
        client.post(
            "/api/test/grade",
            json={
                "node_id": "0.1",
                "qid": "q1",
                "question": "q",
                "expected_points": [],
                "qtype": "concept",
                "answer": "a",
            },
        ).json()["score"]
        == 1.0
    )
    assert client.get("/api/stats").json()["total_nodes"] == 2


def test_create_app_web_entrypoint(sample_plan):
    client = TestClient(create_app())

    assert client.get("/").status_code == 200
    assert client.get("/api/health").json()["ok"] is True
    assert client.get("/api/deployment").json()["deployment"]["mode"]


def test_ask_route_passes_tutor_mode(sample_plan, monkeypatch):
    seen = {}

    def fake_ask(node, stage_name, question, **kwargs):
        seen["mode"] = kwargs.get("mode")
        return "answer", []

    monkeypatch.setattr(study.tutor, "ask", fake_ask)
    client = TestClient(create_app())

    response = client.post(
        "/api/ask",
        json={"question": "解释 PPO", "mode": "check_understanding"},
    )

    assert response.status_code == 200
    assert seen["mode"] == "check_understanding"


def test_advance_route_returns_gate_reasons(sample_plan):
    client = TestClient(create_app())

    response = client.post("/api/advance", json={})

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["message"] == "当前节点未满足推进门槛。"
    assert detail["reasons"]


def test_sources_route_can_save_config(sample_plan):
    client = TestClient(create_app())

    response = client.put(
        "/api/sources",
        json={
            "sources": [
                {
                    "id": "local-notes",
                    "type": "local_directory",
                    "name": "Local Notes",
                    "enabled": True,
                    "priority": "core",
                    "config": {"path": "library/manual"},
                }
            ]
        },
    )

    assert response.status_code == 200
    assert any(source["id"] == "local-notes" for source in response.json()["sources"])


def test_llm_runtime_error_returns_json(monkeypatch):
    monkeypatch.setattr(
        learning,
        "create_plan",
        lambda goal, level: (_ for _ in ()).throw(
            RuntimeError("ANTHROPIC_API_KEY not set")
        ),
    )
    client = TestClient(create_app())

    response = client.post("/api/plan", json={"goal": "goal"})

    assert response.status_code == 502
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]


def test_anthropic_permission_error_returns_json(monkeypatch):
    def raise_permission_error(goal, level):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx.Response(
            403,
            request=request,
            json={"error": {"type": "forbidden", "message": "Request not allowed"}},
        )
        raise PermissionDeniedError("forbidden", response=response, body=response.json())

    monkeypatch.setattr(learning, "create_plan", raise_permission_error)
    client = TestClient(create_app())

    response = client.post("/api/plan", json={"goal": "goal"})

    assert response.status_code == 502
    body = response.json()
    assert "Request not allowed" in body["detail"]
    assert "model" in body


def test_knowledge_routes(sample_plan, monkeypatch):
    def fake_archive_node(node, stage_name="", use_rag=True):
        from rl_agent_tutor import config

        target = config.workspace_path("library", "notes", f"{node.id}_first.md")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# node", encoding="utf-8")
        return target

    def fake_build_index(plan):
        from rl_agent_tutor import config

        target = config.workspace_path("library", "notes", "INDEX.md")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# index", encoding="utf-8")
        return target

    monkeypatch.setattr(knowledge.archivist, "archive_node", fake_archive_node)
    monkeypatch.setattr(knowledge.archivist, "build_index", fake_build_index)

    client = TestClient(app)
    assert client.post("/api/archive", json={}).status_code == 200
    assert client.get("/api/kb").json()["markdown"] == "# index"
    assert client.get("/api/kb/0.1").json()["markdown"] == "# node"
