"""Text storage backends for local and cloud deployments.

`store.py` persists domain state as a handful of JSON/JSONL text documents.
This module keeps that contract and swaps the document backend based on
deployment configuration:

- local filesystem for Local Full Mode
- Postgres for durable cloud state
- Vercel KV / Upstash REST for lightweight cloud state
- Vercel Blob for artifact-like text documents
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

import httpx

from . import config
from .deployment import profile


class TextStorage(Protocol):
    backend_name: str

    def exists(self, key: str) -> bool: ...
    def read_text(self, key: str) -> str: ...
    def write_text(self, key: str, text: str) -> None: ...
    def append_text(self, key: str, text: str) -> None: ...


def storage_status() -> dict:
    prof = profile()
    backend = get_text_storage()
    return {
        "backend": prof.storage_backend,
        "active_text_backend": backend.backend_name,
        "cloud_ready": prof.capabilities["cloud_persistence"],
        "mode": prof.mode,
        "notes": _notes(prof.storage_backend),
    }


def get_text_storage() -> TextStorage:
    backend = profile().storage_backend
    if backend == "postgres":
        return PostgresTextStorage()
    if backend == "vercel-kv":
        return VercelKVTextStorage()
    if backend == "vercel-blob":
        return VercelBlobTextStorage()
    return LocalTextStorage()


def reset_storage_cache() -> None:
    """Compatibility no-op kept for tests that need to switch env vars."""


class LocalTextStorage:
    backend_name = "local-filesystem"

    def exists(self, key: str) -> bool:
        return _path_for_key(key).exists()

    def read_text(self, key: str) -> str:
        return _path_for_key(key).read_text(encoding="utf-8")

    def write_text(self, key: str, text: str) -> None:
        path = _path_for_key(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)

    def append_text(self, key: str, text: str) -> None:
        path = _path_for_key(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())


class PostgresTextStorage:
    backend_name = "postgres"

    def __init__(self) -> None:
        self.dsn = os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL") or ""
        if not self.dsn:
            raise RuntimeError("Postgres storage selected but POSTGRES_URL/DATABASE_URL is missing")

    def exists(self, key: str) -> bool:
        return self.read_text(key) != ""

    def read_text(self, key: str) -> str:
        self._ensure_table()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("select value from rl_agent_documents where key = %s", (_scoped_key(key),))
                row = cur.fetchone()
                return row[0] if row else ""

    def write_text(self, key: str, text: str) -> None:
        self._ensure_table()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into rl_agent_documents(key, value, updated_at)
                    values (%s, %s, now())
                    on conflict (key) do update set value = excluded.value, updated_at = now()
                    """,
                    (_scoped_key(key), text),
                )
            conn.commit()

    def append_text(self, key: str, text: str) -> None:
        current = self.read_text(key)
        self.write_text(key, current + text)

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("Postgres storage requires optional dependency `psycopg`.") from exc
        return psycopg.connect(self.dsn)

    def _ensure_table(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    create table if not exists rl_agent_documents (
                        key text primary key,
                        value text not null,
                        updated_at timestamptz not null default now()
                    )
                    """
                )
            conn.commit()


class VercelKVTextStorage:
    backend_name = "vercel-kv"

    def __init__(self) -> None:
        self.url = os.getenv("KV_REST_API_URL", "").rstrip("/")
        self.token = os.getenv("KV_REST_API_TOKEN", "")
        if not self.url or not self.token:
            raise RuntimeError("Vercel KV storage selected but KV_REST_API_URL/KV_REST_API_TOKEN is missing")

    def exists(self, key: str) -> bool:
        return self.read_text(key) != ""

    def read_text(self, key: str) -> str:
        result = self._command(["GET", _scoped_key(key)])
        return result if isinstance(result, str) else ""

    def write_text(self, key: str, text: str) -> None:
        self._command(["SET", _scoped_key(key), text])

    def append_text(self, key: str, text: str) -> None:
        self._command(["APPEND", _scoped_key(key), text])

    def _command(self, payload: list):
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(
                self.url,
                headers={"Authorization": f"Bearer {self.token}"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("result")


class VercelBlobTextStorage:
    backend_name = "vercel-blob"

    def __init__(self) -> None:
        self.token = os.getenv("BLOB_READ_WRITE_TOKEN") or os.getenv("VERCEL_BLOB_TOKEN") or ""
        self.base_url = os.getenv("VERCEL_BLOB_BASE_URL", "https://blob.vercel-storage.com").rstrip("/")
        if not self.token:
            raise RuntimeError("Vercel Blob storage selected but BLOB_READ_WRITE_TOKEN/VERCEL_BLOB_TOKEN is missing")

    def exists(self, key: str) -> bool:
        return self.read_text(key) != ""

    def read_text(self, key: str) -> str:
        url = f"{self.base_url}/{_blob_key(key)}"
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(url, headers={"Authorization": f"Bearer {self.token}"})
            if resp.status_code == 404:
                return ""
            resp.raise_for_status()
            return resp.text

    def write_text(self, key: str, text: str) -> None:
        url = f"{self.base_url}/{_blob_key(key)}"
        with httpx.Client(timeout=20.0) as client:
            resp = client.put(
                url,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "text/plain; charset=utf-8",
                    "x-add-random-suffix": "0",
                    "x-allow-overwrite": "1",
                },
                content=text.encode("utf-8"),
            )
            resp.raise_for_status()

    def append_text(self, key: str, text: str) -> None:
        self.write_text(key, self.read_text(key) + text)


def _path_for_key(key: str) -> Path:
    return config.workspace_path(*Path(key).parts)


def _scoped_key(key: str) -> str:
    return f"{config.workspace_name()}:{key}"


def _blob_key(key: str) -> str:
    safe_workspace = config.workspace_name().replace("/", "_")
    return f"rl-agent-tutor/{safe_workspace}/{key}".replace("\\", "/")


def _notes(backend: str) -> list[str]:
    if backend == "postgres":
        return ["Postgres is active for plan, trajectory, resources, and exercises documents."]
    if backend == "vercel-blob":
        return ["Vercel Blob is active for plan, trajectory, resources, and exercises documents."]
    if backend == "vercel-kv":
        return ["Vercel KV is active for plan, trajectory, resources, and exercises documents."]
    if backend == "ephemeral":
        return ["No cloud storage credentials detected; Vercel mode falls back to ephemeral /tmp."]
    return ["Local filesystem is the durable store in Local Full Mode."]
