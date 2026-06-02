"""Deployment-mode and persistence capability reporting."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DeploymentProfile:
    mode: str
    storage_backend: str
    capabilities: dict[str, bool]
    warnings: list[str]

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "storage_backend": self.storage_backend,
            "capabilities": self.capabilities,
            "warnings": self.warnings,
        }


def profile() -> DeploymentProfile:
    forced = os.getenv("RL_AGENT_MODE", "").strip().lower()
    mode = forced or ("vercel-demo" if os.getenv("VERCEL") else "local-full")
    storage_backend = _storage_backend()
    capabilities = {
        "daemon": mode == "local-full",
        "git_clone": mode == "local-full",
        "local_rag": mode == "local-full",
        "filesystem_persistence": mode == "local-full" or storage_backend != "ephemeral",
        "cloud_persistence": storage_backend in {"postgres", "vercel-blob", "vercel-kv", "cloud"},
    }
    warnings = []
    if mode == "vercel-demo" and storage_backend == "ephemeral":
        warnings.append("Vercel Demo Mode uses ephemeral /tmp storage; data may disappear between function instances.")
    if mode == "vercel-demo" and not capabilities["git_clone"]:
        warnings.append("git clone, daemon, and long-lived local RAG are disabled or degraded in demo mode.")
    return DeploymentProfile(mode=mode, storage_backend=storage_backend, capabilities=capabilities, warnings=warnings)


def _storage_backend() -> str:
    explicit = os.getenv("RL_AGENT_STORAGE", "").strip().lower()
    if explicit:
        return explicit
    if os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL"):
        return "postgres"
    if os.getenv("BLOB_READ_WRITE_TOKEN") or os.getenv("VERCEL_BLOB_TOKEN"):
        return "vercel-blob"
    if os.getenv("KV_REST_API_URL") and os.getenv("KV_REST_API_TOKEN"):
        return "vercel-kv"
    if os.getenv("VERCEL"):
        return "ephemeral"
    return "local-filesystem"
