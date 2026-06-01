"""Trajectory and dashboard stats API routes."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter

from ..llm import provider_info
from ..store import load_exercises, load_plan, load_trajectory


router = APIRouter()


@router.get("/api/trajectory")
def get_trajectory(node_id: Optional[str] = None, limit: int = 50):
    return {"entries": [e.model_dump() for e in load_trajectory(node_id=node_id, limit=limit)]}


@router.get("/api/stats")
def get_stats():
    plan = load_plan()
    if not plan:
        return {"empty": True}
    nodes = plan.all_nodes()
    done = sum(1 for node in nodes if node.status == "completed")

    all_traj = load_trajectory(limit=100000)
    by_day: dict[str, int] = {}
    for entry in all_traj:
        day = entry.ts[:10]
        by_day[day] = by_day.get(day, 0) + 1

    today = date.today()
    streak = 0
    for i in range(0, 365):
        day = (today - timedelta(days=i)).isoformat()
        if by_day.get(day, 0) > 0:
            streak += 1
        elif i > 0:
            break

    exercises = load_exercises()
    scores = [
        {"date": session.started_at[:10], "node": session.node_id, "score": session.overall_score}
        for session in exercises
        if session.overall_score is not None
    ]
    return {
        "total_nodes": len(nodes),
        "done_nodes": done,
        "by_day": by_day,
        "streak": streak,
        "scores": scores,
        "current_node_id": plan.current_node_id,
        "state": plan.state,
        "provider": provider_info(),
    }
