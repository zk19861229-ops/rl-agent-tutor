"""Tutor, practice, and courseware API routes."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import courseware, practice, tutor
from ..models import TrajectoryEntry
from ..store import append_trajectory
from ..services import learning as learning_service


router = APIRouter()


class AskReq(BaseModel):
    question: str


def _plan_or_404():
    try:
        return learning_service.require_plan()
    except learning_service.PlanNotFoundError:
        raise HTTPException(404, "No plan yet. Create one via POST /api/plan.")


@router.post("/api/ask")
async def post_ask(req: AskReq):
    plan = _plan_or_404()
    if not plan.current_node_id:
        raise HTTPException(400, "no current node")
    node = plan.find_node(plan.current_node_id)
    stage = plan.stage_of(node.id)
    append_trajectory(TrajectoryEntry(node_id=node.id, kind="ask", content=req.question))
    answer, citations = await asyncio.to_thread(
        tutor.ask,
        node,
        stage.name if stage else "",
        req.question,
    )
    append_trajectory(
        TrajectoryEntry(
            node_id=node.id,
            kind="answer",
            content=answer,
            meta={"citations": citations},
        )
    )
    return {"answer": answer, "citations": citations}


@router.post("/api/practices")
async def post_practices():
    plan = _plan_or_404()
    node = plan.find_node(plan.current_node_id)
    if not node:
        raise HTTPException(400, "no current node")
    text = await asyncio.to_thread(practice.best_practices, node)
    append_trajectory(
        TrajectoryEntry(
            node_id=node.id,
            kind="study",
            content=f"viewed practices: {node.name}",
        )
    )
    return {"text": text}


@router.post("/api/courseware")
async def post_courseware(force: bool = False):
    """Generate (or load cached) courseware for the current node from fetched resources."""
    plan = _plan_or_404()
    node = plan.find_node(plan.current_node_id)
    if not node:
        raise HTTPException(400, "no current node")
    stage = plan.stage_of(node.id)
    if not force:
        cached = courseware.load_courseware(node)
        if cached:
            return cached
    result = await asyncio.to_thread(
        courseware.generate_courseware,
        node,
        stage.name if stage else "",
    )
    append_trajectory(
        TrajectoryEntry(
            node_id=node.id,
            kind="study",
            content=f"generated courseware: {node.name}",
            meta={"sources_used": result.get("sources_used")},
        )
    )
    return result


@router.get("/api/courseware/{node_id}")
def get_courseware(node_id: str):
    plan = _plan_or_404()
    node = plan.find_node(node_id)
    if not node:
        raise HTTPException(404, f"node {node_id} not found")
    cached = courseware.load_courseware(node)
    if not cached:
        return {"node_id": node_id, "markdown": "", "cached": False}
    return cached
