"""Self-test API routes."""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import examiner
from ..models import ExerciseQuestion
from ..services import learning as learning_service
from ..services import testing as testing_service


router = APIRouter()


class TestStartReq(BaseModel):
    node_id: Optional[str] = None  # default: current


class TestGradeReq(BaseModel):
    node_id: str
    qid: str
    question: str
    expected_points: list[str]
    qtype: str
    answer: str


class TestSubmitReq(BaseModel):
    node_id: str
    questions: list[dict]
    attempts: list[dict]


def _plan_or_404():
    try:
        return learning_service.require_plan()
    except learning_service.PlanNotFoundError:
        raise HTTPException(404, "No plan yet. Create one via POST /api/plan.")


@router.post("/api/test/start")
async def post_test_start(req: TestStartReq):
    plan = _plan_or_404()
    node_id = req.node_id or plan.current_node_id
    node = plan.find_node(node_id)
    if not node:
        raise HTTPException(404, f"node {node_id} not found")
    questions = await asyncio.to_thread(examiner.generate_exercises, node)
    testing_service.mark_self_testing()
    return {"node_id": node.id, "questions": [q.model_dump() for q in questions]}


@router.post("/api/test/grade")
async def post_test_grade(req: TestGradeReq):
    question = ExerciseQuestion(
        qid=req.qid,
        type=req.qtype,
        question=req.question,
        expected_points=req.expected_points,
    )
    attempt = await asyncio.to_thread(examiner.grade_answer, question, req.answer)
    return attempt.model_dump()


@router.post("/api/test/submit")
def post_test_submit(req: TestSubmitReq):
    """Persist the entire session at the end."""
    try:
        result = testing_service.submit_from_payload(
            node_id=req.node_id,
            questions=req.questions,
            attempts=req.attempts,
        )
    except learning_service.PlanNotFoundError:
        raise HTTPException(404, "No plan yet. Create one via POST /api/plan.")
    return {
        "overall_score": result.overall_score,
        "summary": result.summary,
        "state": result.plan_state,
    }
