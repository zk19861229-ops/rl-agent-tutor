"""Knowledge-base and review API routes."""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import knowledge as knowledge_service
from ..services import learning as learning_service


router = APIRouter()


class ArchiveReq(BaseModel):
    node_id: Optional[str] = None
    all_completed: bool = False
    all_active: bool = False


@router.post("/api/archive")
async def post_archive(req: ArchiveReq):
    try:
        result = await asyncio.to_thread(
            knowledge_service.archive,
            node_id=req.node_id,
            all_completed=req.all_completed,
            all_active=req.all_active,
        )
    except learning_service.PlanNotFoundError:
        raise HTTPException(404, "No plan yet. Create one via POST /api/plan.")
    except learning_service.NodeNotFoundError:
        node_id = req.node_id or "(current)"
        raise HTTPException(404, f"node {node_id} not found")
    return {
        "files": [str(path) for path in result.archived_files],
        "index": str(result.index_file),
    }


@router.get("/api/kb")
def get_kb_index():
    try:
        markdown = knowledge_service.read_kb_index()
    except learning_service.PlanNotFoundError:
        raise HTTPException(404, "No plan yet. Create one via POST /api/plan.")
    if markdown is None:
        return {"markdown": "(no KB yet — run archive first)"}
    return {"markdown": markdown}


@router.get("/api/kb/{node_id}")
def get_kb_node(node_id: str):
    try:
        markdown = knowledge_service.read_kb_node(node_id)
    except learning_service.PlanNotFoundError:
        raise HTTPException(404, "No plan yet. Create one via POST /api/plan.")
    except learning_service.NodeNotFoundError:
        raise HTTPException(404, f"node {node_id} not found")
    if markdown is None:
        return {"markdown": f"(no KB entry for {node_id} yet — POST /api/archive first)"}
    return {"markdown": markdown}


@router.post("/api/review/weekly")
async def post_weekly_review():
    try:
        target = await asyncio.to_thread(knowledge_service.weekly_review)
    except learning_service.PlanNotFoundError:
        raise HTTPException(404, "No plan yet. Create one via POST /api/plan.")
    return {"file": str(target), "markdown": target.read_text(encoding="utf-8")}


@router.post("/api/review/weekly/apply")
def post_apply_weekly_review():
    try:
        return knowledge_service.apply_latest_weekly_review()
    except learning_service.PlanNotFoundError:
        raise HTTPException(404, "No plan yet. Create one via POST /api/plan.")
