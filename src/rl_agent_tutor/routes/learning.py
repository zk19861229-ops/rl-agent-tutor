"""Plan and navigation API routes."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..llm import provider_info
from ..services import learning as learning_service


router = APIRouter()


class PlanReq(BaseModel):
    goal: str
    level: str = ""


class GotoReq(BaseModel):
    node_id: str


class AdvanceReq(BaseModel):
    force: bool = False
    reason: str = ""


@router.get("/api/plan")
def get_plan():
    status = learning_service.get_plan_status()
    if not status:
        return {"plan": None, "provider": provider_info()}
    return {
        "plan": status.plan.model_dump(),
        "provider": provider_info(),
        "next_action": status.next_action,
        "recommended_action": status.recommended_action.to_dict(),
    }


@router.post("/api/plan")
async def post_plan(req: PlanReq):
    plan = await asyncio.to_thread(learning_service.create_plan, req.goal, req.level)
    return {"plan": plan.model_dump()}


@router.post("/api/goto")
def post_goto(req: GotoReq):
    try:
        plan = learning_service.goto_node(req.node_id)
    except learning_service.PlanNotFoundError:
        raise HTTPException(404, "No plan yet. Create one via POST /api/plan.")
    except learning_service.NodeNotFoundError:
        raise HTTPException(404, f"node {req.node_id} not found")
    return {"plan": plan.model_dump()}


@router.post("/api/advance")
def post_advance(req: AdvanceReq | None = None):
    req = req or AdvanceReq()
    try:
        result = learning_service.advance_current_node(force=req.force, reason=req.reason)
    except learning_service.PlanNotFoundError:
        raise HTTPException(404, "No plan yet. Create one via POST /api/plan.")
    except learning_service.NoCurrentNodeError as e:
        raise HTTPException(400, str(e))
    except learning_service.AdvanceBlockedError as e:
        raise HTTPException(
            409,
            {
                "message": "当前节点未满足推进门槛。",
                "node_id": e.node_id,
                "reasons": e.reasons,
            },
        )
    return {
        "completed": result.completed_node_id,
        "next": result.next_node_id,
        "plan": result.plan.model_dump(),
        "gate": result.gate.to_dict(),
    }
