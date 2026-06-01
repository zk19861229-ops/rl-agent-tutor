"""FastAPI Web UI entrypoint — single-page dashboard.

Endpoints:
- GET  /              → HTML dashboard
- GET  /api/plan      → current plan + state
- POST /api/plan      → create new plan {goal, level}
- POST /api/ask       → {question} → tutor answer (streams not used in MVP)
- POST /api/fetch     → fetch resources for current node
- GET  /api/resources/{node_id}
- POST /api/test/start → {node_id} returns generated questions
- POST /api/test/grade → {qid, answer, ...session_id} returns feedback
- POST /api/advance   → mark current node done, move on
- POST /api/goto      → {node_id}
- POST /api/archive   → archive a node (or current)
- GET  /api/kb/{node_id?} → return KB markdown
- POST /api/review/weekly → generate weekly review
- GET  /api/stats     → counts/heatmap data

Run:
- rl-agent serve [--port 8765]
- rl-agent-web [--port 8765]
- uvicorn rl_agent_tutor.server:create_app --factory
"""
from __future__ import annotations
import argparse
from contextlib import asynccontextmanager
from pathlib import Path

from anthropic import APIStatusError
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from . import workspaces as ws_mod
from .llm import provider_info
from .routes.dashboard import router as dashboard_router
from .routes.knowledge import router as knowledge_router
from .routes.learning import router as learning_router
from .routes.library import router as library_router
from .routes.study import router as study_router
from .routes.testing import router as testing_router
from .routes.workspaces import router as workspaces_router


WEB_DIR = Path(__file__).with_name("web")
INDEX_HTML_PATH = WEB_DIR / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure there is at least one workspace and it's active."""
    try:
        ws_mod.ensure_default()
    except Exception as e:
        print(f"[server] startup workspace setup failed: {e}")
    yield


def create_app() -> FastAPI:
    """Build the FastAPI application.

    Keeping app construction in a factory gives CLI, uvicorn, tests, and
    deployment scripts one shared web entrypoint.
    """
    application = FastAPI(title="RL Agent Tutor", version="0.3.0", lifespan=lifespan)
    application.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    application.include_router(dashboard_router)
    application.include_router(workspaces_router)
    application.include_router(knowledge_router)
    application.include_router(learning_router)
    application.include_router(library_router)
    application.include_router(study_router)
    application.include_router(testing_router)

    @application.exception_handler(APIStatusError)
    async def llm_status_error_handler(request, exc: APIStatusError):
        status_code = getattr(exc, "status_code", 502) or 502
        upstream_message = _extract_upstream_message(exc)
        detail = _llm_error_detail(
            f"LLM provider rejected the request ({status_code}): {upstream_message}"
        )
        return JSONResponse(status_code=_http_status_for_llm(status_code), content=detail)

    @application.exception_handler(RuntimeError)
    async def runtime_error_handler(request, exc: RuntimeError):
        message = str(exc)
        if _looks_like_llm_config_error(message):
            return JSONResponse(
                status_code=502,
                content=_llm_error_detail(message),
            )
        raise exc

    @application.get("/api/health")
    def health():
        active = ws_mod.get_active()
        return {
            "ok": True,
            "provider": provider_info(),
            "workspace": active.name if active else None,
        }

    @application.get("/", response_class=HTMLResponse)
    def index():
        return INDEX_HTML_PATH.read_text(encoding="utf-8")

    return application


def _extract_upstream_message(exc: APIStatusError) -> str:
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            data = response.json()
            error = data.get("error", data)
            if isinstance(error, dict):
                return str(error.get("message") or error.get("type") or data)
            return str(error)
        except Exception:
            text = getattr(response, "text", "")
            if text:
                return text[:500]
    return str(exc)


def _http_status_for_llm(upstream_status: int) -> int:
    if upstream_status in {401, 403, 404}:
        return 502
    if upstream_status == 429:
        return 429
    if 400 <= upstream_status < 500:
        return 400
    return 502


def _looks_like_llm_config_error(message: str) -> bool:
    return any(
        marker in message
        for marker in (
            "ANTHROPIC_API_KEY",
            "OPENROUTER_API_KEY",
            "OpenRouter error",
            "LLM_PROVIDER",
        )
    )


def _llm_error_detail(message: str) -> dict:
    return {
        "detail": message,
        "provider": config.LLM_PROVIDER,
        "model": config.OPENROUTER_MODEL
        if config.LLM_PROVIDER == "openrouter"
        else config.ANTHROPIC_MODEL,
        "hint": (
            "Check .env API key and model access. If you see Anthropic 403 "
            "'Request not allowed', switch ANTHROPIC_MODEL to a model your key "
            "can access, for example claude-sonnet-4-5, then restart rl-agent-web."
        ),
    }


app = create_app()


def run(host: str = "127.0.0.1", port: int = 8765, reload: bool = False) -> None:
    """Run the web server from Python/CLI entrypoints."""
    import uvicorn

    uvicorn.run(
        "rl_agent_tutor.server:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
    )


def main(argv: list[str] | None = None) -> None:
    """Console-script entrypoint for `rl-agent-web`."""
    parser = argparse.ArgumentParser(description="Run the RL Agent Tutor Web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", "-p", type=int, default=8765)
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn auto-reload.")
    args = parser.parse_args(argv)
    run(host=args.host, port=args.port, reload=args.reload)
