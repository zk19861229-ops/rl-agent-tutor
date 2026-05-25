"""Persistent state: plan.json, trajectory.jsonl, exercises.jsonl, resources.jsonl."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional
from .config import workspace_path, ensure_workspace
from .models import LearningPlan, TrajectoryEntry, Resource, ExerciseSession


def plan_path() -> Path:
    return workspace_path("progress", "plan.json")


def traj_path() -> Path:
    return workspace_path("progress", "trajectory.jsonl")


def resources_path() -> Path:
    return workspace_path("progress", "resources.jsonl")


def exercises_path() -> Path:
    return workspace_path("progress", "exercises.jsonl")


def save_plan(plan: LearningPlan) -> None:
    ensure_workspace()
    from datetime import datetime
    plan.updated_at = datetime.now().isoformat()
    plan_path().write_text(plan.model_dump_json(indent=2), encoding="utf-8")


def load_plan() -> Optional[LearningPlan]:
    p = plan_path()
    if not p.exists():
        return None
    return LearningPlan.model_validate_json(p.read_text(encoding="utf-8"))


def append_trajectory(entry: TrajectoryEntry) -> None:
    ensure_workspace()
    with traj_path().open("a", encoding="utf-8") as f:
        f.write(entry.model_dump_json() + "\n")


def load_trajectory(node_id: Optional[str] = None, limit: int = 50) -> list[TrajectoryEntry]:
    p = traj_path()
    if not p.exists():
        return []
    entries: list[TrajectoryEntry] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = TrajectoryEntry.model_validate_json(line)
        if node_id and e.node_id != node_id:
            continue
        entries.append(e)
    return entries[-limit:]


def append_resource(r: Resource) -> None:
    ensure_workspace()
    with resources_path().open("a", encoding="utf-8") as f:
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
    with exercises_path().open("a", encoding="utf-8") as f:
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
