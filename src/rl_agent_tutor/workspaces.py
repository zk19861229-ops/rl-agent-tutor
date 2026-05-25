"""Workspace registry — list, create, switch, rename, delete named workspaces.

A workspace is just a directory under WORKSPACES_ROOT containing the usual
library/ and progress/ subtree. The "active" workspace is recorded in
WORKSPACES_ROOT/.active (a one-line text file containing the workspace name).

Names must be safe: lowercase letters, digits, hyphens, underscores; ≤ 40 chars.
"""
from __future__ import annotations
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import config


_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


def _validate_name(name: str) -> str:
    name = (name or "").strip().lower()
    if not _NAME_RE.match(name):
        raise ValueError(
            f"invalid workspace name {name!r}: use lowercase letters, digits, "
            f"`_` or `-`, start with a letter/digit, ≤ 40 chars"
        )
    if name == ".active":
        raise ValueError("name `.active` is reserved")
    return name


@dataclass
class WorkspaceInfo:
    name: str
    path: Path
    active: bool
    has_plan: bool
    goal: str
    progress: tuple[int, int]  # (done, total) nodes
    last_activity: Optional[str]  # ISO date or None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": str(self.path),
            "active": self.active,
            "has_plan": self.has_plan,
            "goal": self.goal,
            "progress": list(self.progress),
            "last_activity": self.last_activity,
        }


def _root() -> Path:
    config.WORKSPACES_ROOT.mkdir(parents=True, exist_ok=True)
    return config.WORKSPACES_ROOT


def _active_file() -> Path:
    return _root() / ".active"


def _read_pointer() -> Optional[str]:
    f = _active_file()
    if not f.exists():
        return None
    return (f.read_text(encoding="utf-8").strip() or None)


def _write_pointer(name: str) -> None:
    _active_file().write_text(name, encoding="utf-8")


def list_workspaces() -> list[WorkspaceInfo]:
    """Return all workspaces in registry order (alphabetical)."""
    root = _root()
    active = _read_pointer()
    out: list[WorkspaceInfo] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        out.append(_inspect(entry, active_name=active))
    return out


def _inspect(ws_path: Path, *, active_name: Optional[str]) -> WorkspaceInfo:
    name = ws_path.name
    plan_file = ws_path / "progress" / "plan.json"
    traj_file = ws_path / "progress" / "trajectory.jsonl"
    has_plan = plan_file.exists()
    goal = ""
    done = total = 0
    if has_plan:
        try:
            import json
            data = json.loads(plan_file.read_text(encoding="utf-8"))
            goal = (data.get("goal") or "")[:120]
            nodes = [n for s in data.get("stages", []) for n in s.get("nodes", [])]
            total = len(nodes)
            done = sum(1 for n in nodes if n.get("status") == "completed")
        except Exception:
            pass
    last = None
    if traj_file.exists():
        try:
            mtime = datetime.fromtimestamp(traj_file.stat().st_mtime)
            last = mtime.date().isoformat()
        except Exception:
            pass
    return WorkspaceInfo(
        name=name, path=ws_path, active=(name == active_name),
        has_plan=has_plan, goal=goal, progress=(done, total),
        last_activity=last,
    )


def get_active() -> Optional[WorkspaceInfo]:
    name = _read_pointer()
    if not name:
        return None
    path = _root() / name
    if not path.exists():
        return None
    return _inspect(path, active_name=name)


def create(name: str, *, switch: bool = True) -> WorkspaceInfo:
    name = _validate_name(name)
    path = _root() / name
    if path.exists():
        raise ValueError(f"workspace {name!r} already exists at {path}")
    for sub in ("library/papers", "library/code",
                "library/notes/blogs", "library/notes/transcripts",
                "library/notes/reviews", "library/notes/nudges",
                "library/index", "progress"):
        (path / sub).mkdir(parents=True, exist_ok=True)
    if switch:
        switch_to(name)
    return _inspect(path, active_name=_read_pointer())


def switch_to(name: str) -> WorkspaceInfo:
    name = _validate_name(name)
    path = _root() / name
    if not path.exists():
        raise ValueError(f"workspace {name!r} doesn't exist. Create it first.")
    _write_pointer(name)
    # update in-process pointer immediately
    config.set_active_workspace(path)
    return _inspect(path, active_name=name)


def rename(old: str, new: str) -> WorkspaceInfo:
    old = _validate_name(old); new = _validate_name(new)
    src = _root() / old
    dst = _root() / new
    if not src.exists():
        raise ValueError(f"workspace {old!r} doesn't exist")
    if dst.exists():
        raise ValueError(f"workspace {new!r} already exists")
    src.rename(dst)
    if _read_pointer() == old:
        _write_pointer(new)
        config.set_active_workspace(dst)
    return _inspect(dst, active_name=_read_pointer())


def delete(name: str, *, force: bool = False) -> None:
    name = _validate_name(name)
    path = _root() / name
    if not path.exists():
        raise ValueError(f"workspace {name!r} doesn't exist")
    if _read_pointer() == name and not force:
        raise ValueError(
            f"refusing to delete active workspace {name!r}. "
            f"switch to another first, or pass force=True"
        )
    shutil.rmtree(path)
    if _read_pointer() == name:
        # active was force-deleted; clear pointer
        _active_file().unlink(missing_ok=True)


def migrate_legacy(legacy_dir: Path = Path("./workspace"), *,
                   new_name: str = "default") -> Optional[WorkspaceInfo]:
    """If `./workspace/` exists (old single-workspace install), move it under
    WORKSPACES_ROOT as `<new_name>` and mark it active. Idempotent."""
    legacy = legacy_dir.expanduser().resolve()
    if not legacy.exists():
        return None
    target = _root() / new_name
    if target.exists():
        return _inspect(target, active_name=_read_pointer())
    shutil.move(str(legacy), str(target))
    _write_pointer(new_name)
    config.set_active_workspace(target)
    return _inspect(target, active_name=new_name)


def ensure_default() -> WorkspaceInfo:
    """Make sure there's at least one workspace and it's active. Used on first run."""
    active = get_active()
    if active:
        return active
    # try migrating legacy first
    migrated = migrate_legacy()
    if migrated:
        return migrated
    # else create a fresh default
    return create("default", switch=True)
