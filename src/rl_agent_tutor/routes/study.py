"""Tutor, practice, and courseware API routes."""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import courseware, practice, tutor
from ..courseware_export import export_courseware
from ..courseware_schema import Courseware
from ..config import workspace_path
from ..models import TrajectoryEntry
from ..store import append_trajectory
from ..services import evidence as evidence_service
from ..services import learning as learning_service
from ..services import workflow as workflow_service


router = APIRouter()


class AskReq(BaseModel):
    question: str
    mode: str = "explain"


class CoursewareSectionReq(BaseModel):
    section_id: str


class CoursewareExportReq(BaseModel):
    node_id: str | None = None
    formats: list[str] = ["markdown", "html", "pdf"]


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
        mode=req.mode,
    )
    append_trajectory(
        TrajectoryEntry(
            node_id=node.id,
            kind="answer",
            content=answer,
            meta={"citations": citations, "mode": req.mode},
        )
    )
    if citations:
        evidence_service.mark_node_resources(
            node.id,
            status="cited",
            used_by="tutor:ask",
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
    if result.get("sources_used"):
        evidence_service.mark_node_resources(
            node.id,
            status="read",
            used_by=f"courseware:{result.get('path', node.id)}",
            only_with_local_content=True,
        )
    return result


@router.post("/api/remediation")
async def post_remediation():
    plan = _plan_or_404()
    node = plan.find_node(plan.current_node_id)
    if not node:
        raise HTTPException(400, "no current node")
    return await asyncio.to_thread(workflow_service.generate_remediation_package, node)


@router.post("/api/courseware/section")
async def post_courseware_section(req: CoursewareSectionReq):
    plan = _plan_or_404()
    node = plan.find_node(plan.current_node_id)
    if not node:
        raise HTTPException(400, "no current node")
    stage = plan.stage_of(node.id)
    try:
        result = await asyncio.to_thread(
            courseware.regenerate_section,
            node,
            req.section_id,
            stage.name if stage else "",
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    append_trajectory(
        TrajectoryEntry(
            node_id=node.id,
            kind="study",
            content=f"regenerated courseware section: {req.section_id}",
        )
    )
    return result


@router.post("/api/courseware/export")
def post_courseware_export(req: CoursewareExportReq):
    plan = _plan_or_404()
    node_id = req.node_id or plan.current_node_id
    node = plan.find_node(node_id) if node_id else None
    if not node:
        raise HTTPException(404, f"node {node_id} not found")
    cached = courseware.load_courseware(node)
    if not cached or not cached.get("courseware"):
        raise HTTPException(404, "courseware not found")
    return export_courseware(Courseware.model_validate(cached["courseware"]), req.formats)


@router.get("/api/courseware/media")
def get_courseware_media(path: str):
    target = Path(path).expanduser().resolve()
    root = workspace_path().resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(403, "media path outside workspace")
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "media not found")
    return FileResponse(target)


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
