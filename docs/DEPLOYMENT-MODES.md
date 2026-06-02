# Deployment Modes

## Local Full Mode

Local Full Mode is the default when `VERCEL` is not set.

Capabilities:
- Durable local filesystem workspaces.
- Local PDF/RAG index.
- `git clone` for GitHub sources.
- Daemon/scheduler workflows.
- Long-running exports and generated artifacts.

Storage backend: local filesystem under the active workspace.

## Vercel Demo Mode

Vercel Demo Mode is active when `VERCEL=1`, unless overridden with
`RL_AGENT_MODE`.

Capabilities are intentionally degraded:
- Files are written under `/tmp/rl-agent-tutor/workspaces`.
- Data is ephemeral unless a cloud backend is configured.
- Daemon/scheduler workflows are not a durable capability.
- `git clone` and long-lived local RAG should be treated as unavailable or
  best-effort demo behavior.

Detected cloud storage:
- `POSTGRES_URL` or `DATABASE_URL` -> `postgres`
- `BLOB_READ_WRITE_TOKEN` or `VERCEL_BLOB_TOKEN` -> `vercel-blob`
- `KV_REST_API_URL` + `KV_REST_API_TOKEN` -> `vercel-kv`

Core business state now goes through the text storage backend:
- `progress/plan.json`
- `progress/trajectory.jsonl`
- `progress/resources.jsonl`
- `progress/exercises.jsonl`
- `progress/source_health.json`

Postgres stores these documents in `rl_agent_documents`. Vercel KV stores them
as scoped keys through the REST API. Vercel Blob stores them as text blobs under
`rl-agent-tutor/<workspace>/...`.

The current runtime exposes this through:

```bash
GET /api/deployment
GET /api/health
```

Use `RL_AGENT_STORAGE` to force a backend label during deployment tests.
