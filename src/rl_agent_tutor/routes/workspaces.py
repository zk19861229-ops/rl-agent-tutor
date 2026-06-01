"""Workspace API routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import workspaces as ws_mod


router = APIRouter()


class WsCreateReq(BaseModel):
    name: str
    switch: bool = True


class WsSwitchReq(BaseModel):
    name: str


@router.get("/api/workspaces")
def get_workspaces():
    active = ws_mod.get_active()
    return {
        "active": active.name if active else None,
        "items": [w.to_dict() for w in ws_mod.list_workspaces()],
    }


@router.post("/api/workspaces")
def create_workspace(req: WsCreateReq):
    try:
        workspace = ws_mod.create(req.name, switch=req.switch)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return workspace.to_dict()


@router.post("/api/workspaces/switch")
def switch_workspace(req: WsSwitchReq):
    try:
        workspace = ws_mod.switch_to(req.name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return workspace.to_dict()


@router.delete("/api/workspaces/{name}")
def delete_workspace(name: str, force: bool = False):
    try:
        ws_mod.delete(name, force=force)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"deleted": name}
