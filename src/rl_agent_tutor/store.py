"""Persistent state: plan.json, trajectory.jsonl, exercises.jsonl, resources.jsonl.

Concurrency model:
- save_plan writes via tmp + os.replace so readers never see a partial JSON file.
- append_* uses fcntl.flock when available so Web UI + Daemon writing the same
  jsonl can't interleave a single line. On Windows we degrade to plain append
  (single-user fallback).
- load_trajectory reverse-reads from the tail to keep cost bounded as the file
  grows past tens of MB.
"""
from __future__ import annotations
import io
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional
from .config import workspace_path, ensure_workspace
from .models import LearningPlan, TrajectoryEntry, Resource, ExerciseSession

try:
    import fcntl  # POSIX only
    _HAS_FCNTL = True
except ImportError:  # pragma: no cover -- Windows fallback
    _HAS_FCNTL = False


def plan_path() -> Path:
    return workspace_path("progress", "plan.json")


def traj_path() -> Path:
    return workspace_path("progress", "trajectory.jsonl")


def resources_path() -> Path:
    return workspace_path("progress", "resources.jsonl")


def exercises_path() -> Path:
    return workspace_path("progress", "exercises.jsonl")


def _atomic_write_text(path: Path, text: str) -> None:
    """Write `text` to `path` atomically: tmp file in same dir, fsync, rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


@contextmanager
def _locked_append(path: Path) -> Iterator[io.TextIOWrapper]:
    """Open `path` in append mode under an exclusive flock (POSIX).

    Ensures concurrent writers (Web UI + Daemon) don't interleave bytes. On
    Windows fcntl is unavailable; falls back to plain append (rl-agent-tutor's
    primary targets are macOS/Linux per PRD §6.1)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    f = path.open("a", encoding="utf-8")
    try:
        if _HAS_FCNTL:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield f
        f.flush()
        os.fsync(f.fileno())
    finally:
        if _HAS_FCNTL:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        f.close()


def save_plan(plan: LearningPlan) -> None:
    ensure_workspace()
    from datetime import datetime
    plan.updated_at = datetime.now().isoformat()
    _atomic_write_text(plan_path(), plan.model_dump_json(indent=2))


def load_plan() -> Optional[LearningPlan]:
    p = plan_path()
    if not p.exists():
        return None
    return LearningPlan.model_validate_json(p.read_text(encoding="utf-8"))


def append_trajectory(entry: TrajectoryEntry) -> None:
    ensure_workspace()
    with _locked_append(traj_path()) as f:
        f.write(entry.model_dump_json() + "\n")


def _tail_lines(path: Path, max_lines: int, block_size: int = 8192) -> list[str]:
    """Return up to `max_lines` non-empty lines from the end of `path`.

    Reads backwards in 8 KiB blocks so cost is O(max_lines), not O(filesize)."""
    if not path.exists():
        return []
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        buf = bytearray()
        lines: list[str] = []
        pos = size
        while pos > 0 and len(lines) <= max_lines:
            read = min(block_size, pos)
            pos -= read
            f.seek(pos)
            chunk = f.read(read)
            buf[:0] = chunk
            # split, but keep the head fragment until we read more bytes
            split = buf.split(b"\n")
            buf = split[0]
            tail = split[1:]
            for raw in reversed(tail):
                if not raw.strip():
                    continue
                lines.append(raw.decode("utf-8", errors="replace"))
                if len(lines) > max_lines * 4:
                    break
        if buf.strip():
            lines.append(buf.decode("utf-8", errors="replace"))
    lines.reverse()  # back to file order
    return lines


def load_trajectory(node_id: Optional[str] = None, limit: int = 50) -> list[TrajectoryEntry]:
    p = traj_path()
    if not p.exists():
        return []
    # Without a node filter we can stop after `limit` lines; with a filter we
    # have to scan further because matches may be sparse. Cap the scan at
    # 20×limit lines from the tail — good enough for a single-user tool.
    raw_lines = _tail_lines(p, max_lines=limit if not node_id else limit * 20)
    entries: list[TrajectoryEntry] = []
    for line in raw_lines:
        if not line.strip():
            continue
        try:
            e = TrajectoryEntry.model_validate_json(line)
        except Exception:
            continue
        if node_id and e.node_id != node_id:
            continue
        entries.append(e)
    return entries[-limit:]


def append_resource(r: Resource) -> None:
    ensure_workspace()
    with _locked_append(resources_path()) as f:
        f.write(r.model_dump_json() + "\n")


def load_resources(node_id: Optional[str] = None) -> list[Resource]:
    p = resources_path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = Resource.model_validate_json(line)
        if node_id and r.node_id != node_id:
            continue
        out.append(r)
    return out


def append_exercise(s: ExerciseSession) -> None:
    ensure_workspace()
    with _locked_append(exercises_path()) as f:
        f.write(s.model_dump_json() + "\n")


def load_exercises(node_id: Optional[str] = None) -> list[ExerciseSession]:
    p = exercises_path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        s = ExerciseSession.model_validate_json(line)
        if node_id and s.node_id != node_id:
            continue
        out.append(s)
    return out
