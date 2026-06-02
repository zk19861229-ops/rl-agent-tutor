"""Configuration, LLM provider, and active workspace resolution.

Active-workspace strategy:
  1) If env `WORKSPACE_DIR` is set → use it directly (power-user / launchd override).
  2) Else read `WORKSPACES_ROOT/.active` to get the active workspace name and use
     `WORKSPACES_ROOT/<name>/`.
  3) Else fall back to `./workspace` for backward compat with single-workspace installs.

`WORKSPACE_DIR` is a module attribute, refreshed via `set_active_workspace()`.
`workspace_path()` reads it at call time, so any code that uses `workspace_path()`
automatically follows switches at runtime.
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# --- LLM provider ---
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").lower()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4.5")
OPENROUTER_REFERER = os.getenv("OPENROUTER_REFERER", "https://github.com/local/rl-agent-tutor")
OPENROUTER_TITLE = os.getenv("OPENROUTER_TITLE", "RL Agent Tutor")


# --- Workspace roots ---

def _default_workspaces_root() -> str:
    # Vercel functions cannot rely on the deployed project directory for writes.
    # This keeps the app bootable as an ephemeral demo until persistent storage
    # is moved to an external backend.
    if os.getenv("VERCEL"):
        return "/tmp/rl-agent-tutor/workspaces"
    return "./workspaces"


# Root that contains all workspace subdirectories + the .active pointer file.
WORKSPACES_ROOT = Path(
    os.getenv("WORKSPACES_ROOT", _default_workspaces_root())
).expanduser().resolve()

# When this env var is set we honor it directly (legacy single-workspace mode,
# or used by daemons that want to pin a specific workspace).
_FORCED_WORKSPACE = os.getenv("WORKSPACE_DIR")


def _active_pointer_file() -> Path:
    return WORKSPACES_ROOT / ".active"


def _read_active_name() -> Optional[str]:
    f = _active_pointer_file()
    if not f.exists():
        return None
    name = f.read_text(encoding="utf-8").strip()
    return name or None


def _resolve_initial_workspace_dir() -> Path:
    if _FORCED_WORKSPACE:
        return Path(_FORCED_WORKSPACE).expanduser().resolve()
    name = _read_active_name()
    if name:
        return WORKSPACES_ROOT / name
    # backward compat: a pre-existing ./workspace/ from single-mode installs
    legacy = Path("./workspace").expanduser().resolve()
    if legacy.exists():
        return legacy
    # default: workspaces/default/
    return WORKSPACES_ROOT / "default"


WORKSPACE_DIR: Path = _resolve_initial_workspace_dir()


def set_active_workspace(path: Path) -> None:
    """Point the running process at a different workspace.
    Note: this updates the in-process module attribute. Other processes won't
    see the change until they re-read the .active pointer (or are restarted)."""
    global WORKSPACE_DIR
    WORKSPACE_DIR = path.expanduser().resolve()


def ensure_workspace() -> Path:
    """Create the workspace directory tree if it doesn't exist."""
    for sub in ("library/papers", "library/code", "library/notes",
                "library/notes/blogs", "library/notes/transcripts",
                "library/notes/reviews", "library/notes/nudges",
                "library/index", "progress"):
        (WORKSPACE_DIR / sub).mkdir(parents=True, exist_ok=True)
    return WORKSPACE_DIR


def workspace_path(*parts: str) -> Path:
    return WORKSPACE_DIR.joinpath(*parts)


def workspace_name() -> str:
    """Best-effort name for the currently active workspace."""
    if _FORCED_WORKSPACE:
        return f"(env: {WORKSPACE_DIR.name})"
    try:
        rel = WORKSPACE_DIR.relative_to(WORKSPACES_ROOT)
        return rel.parts[0] if rel.parts else WORKSPACE_DIR.name
    except ValueError:
        return WORKSPACE_DIR.name
