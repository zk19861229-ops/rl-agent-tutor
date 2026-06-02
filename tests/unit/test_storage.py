from __future__ import annotations

from rl_agent_tutor.models import LearningNode, LearningPlan, Stage, TrajectoryEntry
from rl_agent_tutor import store
import sys
import types


class _FakeResponse:
    def __init__(self, result=None, text="", status_code=200):
        self._result = result
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return {"result": self._result}


class _FakeKVClient:
    data = {}

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, headers=None, json=None):
        cmd, key, *rest = json
        if cmd == "GET":
            return _FakeResponse(self.data.get(key))
        if cmd == "SET":
            self.data[key] = rest[0]
            return _FakeResponse("OK")
        if cmd == "APPEND":
            self.data[key] = self.data.get(key, "") + rest[0]
            return _FakeResponse(len(self.data[key]))
        raise AssertionError(cmd)


class _FakeBlobClient:
    data = {}

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, headers=None):
        if url not in self.data:
            return _FakeResponse(status_code=404)
        return _FakeResponse(text=self.data[url])

    def put(self, url, headers=None, content=b""):
        self.data[url] = content.decode("utf-8")
        return _FakeResponse("OK")


def test_store_uses_vercel_kv_backend(workspace, monkeypatch):
    _FakeKVClient.data = {}
    monkeypatch.setenv("RL_AGENT_STORAGE", "vercel-kv")
    monkeypatch.setenv("KV_REST_API_URL", "https://kv.example")
    monkeypatch.setenv("KV_REST_API_TOKEN", "token")
    monkeypatch.setattr("rl_agent_tutor.storage.httpx.Client", _FakeKVClient)
    plan = LearningPlan(
        goal="cloud",
        current_node_id="0.1",
        stages=[Stage(id=0, name="s", nodes=[LearningNode(id="0.1", name="n", description="")])],
    )

    store.save_plan(plan)
    store.append_trajectory(TrajectoryEntry(node_id="0.1", kind="ask", content="q"))

    assert store.load_plan().goal == "cloud"
    assert store.load_trajectory("0.1")[0].content == "q"


def test_blob_storage_roundtrip(monkeypatch):
    from rl_agent_tutor.storage import VercelBlobTextStorage

    _FakeBlobClient.data = {}
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "token")
    monkeypatch.setenv("VERCEL_BLOB_BASE_URL", "https://blob.example")
    monkeypatch.setattr("rl_agent_tutor.storage.httpx.Client", _FakeBlobClient)

    storage = VercelBlobTextStorage()
    storage.write_text("progress/example.txt", "hello")
    storage.append_text("progress/example.txt", " world")

    assert storage.read_text("progress/example.txt") == "hello world"


def test_postgres_storage_roundtrip(monkeypatch):
    from rl_agent_tutor.storage import PostgresTextStorage

    data = {}

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=None):
            self.row = None
            lowered = sql.lower()
            if lowered.startswith("select"):
                self.row = (data[params[0]],) if params[0] in data else None
            elif "insert into rl_agent_documents" in lowered:
                data[params[0]] = params[1]

        def fetchone(self):
            return self.row

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return Cursor()

        def commit(self):
            pass

    fake_psycopg = types.SimpleNamespace(connect=lambda dsn: Conn())
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)
    monkeypatch.setenv("POSTGRES_URL", "postgres://example")

    storage = PostgresTextStorage()
    storage.write_text("progress/example.txt", "hello")
    storage.append_text("progress/example.txt", " world")

    assert storage.read_text("progress/example.txt") == "hello world"
