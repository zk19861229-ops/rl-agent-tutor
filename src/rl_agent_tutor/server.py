"""FastAPI Web UI — single-page dashboard.

Endpoints:
- GET  /              → HTML dashboard
- GET  /api/plan      → current plan + state
- POST /api/plan      → create new plan {goal, level}
- POST /api/ask       → {question} → tutor answer (streams not used in MVP)
- POST /api/fetch     → fetch resources for current node
- GET  /api/resources/{node_id}
- POST /api/test/start → {node_id} returns generated questions
- POST /api/test/grade → {qid, answer, ...session_id} returns feedback
- POST /api/advance   → mark current node done, move on
- POST /api/goto      → {node_id}
- POST /api/archive   → archive a node (or current)
- GET  /api/kb/{node_id?} → return KB markdown
- POST /api/review/weekly → generate weekly review
- GET  /api/stats     → counts/heatmap data

Run: rl-agent serve [--port 8765]
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import workspace_path, ensure_workspace
from . import workspaces as ws_mod
from .store import (
    save_plan, load_plan, append_trajectory, load_trajectory,
    load_resources, append_exercise, load_exercises, append_resource,
)
from .models import TrajectoryEntry, ExerciseSession, ExerciseAttempt, LearningPlan
from . import planner, librarian, tutor, examiner, practice, archivist, reviewer, orchestrator, courseware
from .archivist import _slugify
from .llm import provider_info


app = FastAPI(title="RL Agent Tutor", version="0.3.0")


# ---------- Models ----------

class PlanReq(BaseModel):
    goal: str
    level: str = ""


class AskReq(BaseModel):
    question: str


class GotoReq(BaseModel):
    node_id: str


class TestStartReq(BaseModel):
    node_id: Optional[str] = None  # default: current


class TestGradeReq(BaseModel):
    node_id: str
    qid: str
    question: str
    expected_points: list[str]
    qtype: str
    answer: str


# ---------- API ----------

def _plan_or_404() -> LearningPlan:
    p = load_plan()
    if not p:
        raise HTTPException(404, "No plan yet. Create one via POST /api/plan.")
    return p


@app.get("/api/health")
def health():
    active = ws_mod.get_active()
    return {
        "ok": True,
        "provider": provider_info(),
        "workspace": active.name if active else None,
    }


@app.on_event("startup")
def _on_startup():
    """Ensure there is at least one workspace and it's active."""
    try:
        ws_mod.ensure_default()
    except Exception as e:
        print(f"[server] startup workspace setup failed: {e}")


# ---------- workspaces ----------

@app.get("/api/workspaces")
def get_workspaces():
    return {
        "active": (ws_mod.get_active().name if ws_mod.get_active() else None),
        "items": [w.to_dict() for w in ws_mod.list_workspaces()],
    }


class WsCreateReq(BaseModel):
    name: str
    switch: bool = True


@app.post("/api/workspaces")
def create_workspace(req: WsCreateReq):
    try:
        w = ws_mod.create(req.name, switch=req.switch)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return w.to_dict()


class WsSwitchReq(BaseModel):
    name: str


@app.post("/api/workspaces/switch")
def switch_workspace(req: WsSwitchReq):
    try:
        w = ws_mod.switch_to(req.name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return w.to_dict()


@app.delete("/api/workspaces/{name}")
def delete_workspace(name: str, force: bool = False):
    try:
        ws_mod.delete(name, force=force)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"deleted": name}


@app.get("/api/plan")
def get_plan():
    p = load_plan()
    if not p:
        return {"plan": None, "provider": provider_info()}
    return {"plan": p.model_dump(), "provider": provider_info(),
            "next_action": orchestrator.suggest_next_action(p)}


@app.post("/api/plan")
async def post_plan(req: PlanReq):
    ensure_workspace()
    plan = await asyncio.to_thread(planner.make_plan, req.goal, req.level)
    save_plan(plan)
    append_trajectory(TrajectoryEntry(kind="plan", content=f"Goal: {req.goal}",
                                      meta={"level": req.level}))
    return {"plan": plan.model_dump()}


@app.post("/api/goto")
def post_goto(req: GotoReq):
    p = _plan_or_404()
    n = p.find_node(req.node_id)
    if not n:
        raise HTTPException(404, f"node {req.node_id} not found")
    p.current_node_id = n.id
    if n.status == "pending":
        n.status = "in_progress"
    p.state = "studying"
    save_plan(p)
    return {"plan": p.model_dump()}


@app.post("/api/ask")
async def post_ask(req: AskReq):
    p = _plan_or_404()
    if not p.current_node_id:
        raise HTTPException(400, "no current node")
    n = p.find_node(p.current_node_id)
    s = p.stage_of(n.id)
    append_trajectory(TrajectoryEntry(node_id=n.id, kind="ask", content=req.question))
    ans, citations = await asyncio.to_thread(tutor.ask, n, s.name if s else "", req.question)
    append_trajectory(TrajectoryEntry(node_id=n.id, kind="answer", content=ans,
                                      meta={"citations": citations}))
    return {"answer": ans, "citations": citations}


class IndexReq(BaseModel):
    pass


@app.post("/api/index")
async def post_index():
    from . import indexer
    n_pdfs, n_chunks, failures = await asyncio.to_thread(indexer.index_papers)
    return {"n_pdfs": n_pdfs, "n_chunks": n_chunks,
            "failures": [{"file": f, "error": e} for f, e in failures],
            "stats": indexer.index_stats()}


@app.get("/api/index/stats")
def get_index_stats():
    from . import indexer
    return indexer.index_stats()


class QueryReq(BaseModel):
    query: str
    top_n: int = 5
    rerank: bool = True


@app.post("/api/query")
async def post_query(req: QueryReq):
    from . import rag
    hits = await asyncio.to_thread(rag.retrieve, req.query, top_n=req.top_n, rerank=req.rerank)
    return {
        "hits": [
            {
                "chunk_id": h.chunk.chunk_id, "doc_id": h.chunk.doc_id,
                "title": h.chunk.title, "section": h.chunk.section,
                "page": h.chunk.page, "score": round(h.score, 3),
                "preview": h.chunk.text[:600],
            }
            for h in hits
        ]
    }


@app.post("/api/fetch")
async def post_fetch():
    p = _plan_or_404()
    if not p.current_node_id:
        raise HTTPException(400, "no current node")
    n = p.find_node(p.current_node_id)
    rs = await asyncio.to_thread(librarian.fetch_for_node, n)
    append_trajectory(TrajectoryEntry(node_id=n.id, kind="fetch",
                                      content=f"fetched {len(rs)} resources"))
    return {"resources": [r.model_dump() for r in rs]}


@app.get("/api/resources/{node_id}")
def get_resources(node_id: str):
    return {"resources": [r.model_dump() for r in load_resources(node_id=node_id)]}


@app.post("/api/practices")
async def post_practices():
    p = _plan_or_404()
    n = p.find_node(p.current_node_id)
    if not n:
        raise HTTPException(400, "no current node")
    text = await asyncio.to_thread(practice.best_practices, n)
    append_trajectory(TrajectoryEntry(node_id=n.id, kind="study",
                                      content=f"viewed practices: {n.name}"))
    return {"text": text}


@app.post("/api/courseware")
async def post_courseware(force: bool = False):
    """Generate (or load cached) courseware for the current node from fetched resources."""
    p = _plan_or_404()
    n = p.find_node(p.current_node_id)
    if not n:
        raise HTTPException(400, "no current node")
    s = p.stage_of(n.id)
    if not force:
        cached = courseware.load_courseware(n)
        if cached:
            return cached
    result = await asyncio.to_thread(courseware.generate_courseware, n, s.name if s else "")
    append_trajectory(TrajectoryEntry(
        node_id=n.id, kind="study",
        content=f"generated courseware: {n.name}",
        meta={"sources_used": result.get("sources_used")},
    ))
    return result


@app.get("/api/courseware/{node_id}")
def get_courseware(node_id: str):
    p = _plan_or_404()
    n = p.find_node(node_id)
    if not n:
        raise HTTPException(404, f"node {node_id} not found")
    cached = courseware.load_courseware(n)
    if not cached:
        return {"node_id": node_id, "markdown": "", "cached": False}
    return cached


@app.post("/api/test/start")
async def post_test_start(req: TestStartReq):
    p = _plan_or_404()
    nid = req.node_id or p.current_node_id
    n = p.find_node(nid)
    if not n:
        raise HTTPException(404, f"node {nid} not found")
    qs = await asyncio.to_thread(examiner.generate_exercises, n)
    p.state = "self_testing"
    save_plan(p)
    return {"node_id": n.id, "questions": [q.model_dump() for q in qs]}


@app.post("/api/test/grade")
async def post_test_grade(req: TestGradeReq):
    from .models import ExerciseQuestion
    q = ExerciseQuestion(qid=req.qid, type=req.qtype, question=req.question,
                         expected_points=req.expected_points)
    attempt = await asyncio.to_thread(examiner.grade_answer, q, req.answer)
    return attempt.model_dump()


class TestSubmitReq(BaseModel):
    node_id: str
    questions: list[dict]
    attempts: list[dict]


@app.post("/api/test/submit")
def post_test_submit(req: TestSubmitReq):
    """Persist the entire session at the end."""
    from .models import ExerciseQuestion
    sess = ExerciseSession(
        node_id=req.node_id,
        questions=[ExerciseQuestion(**q) for q in req.questions],
        attempts=[ExerciseAttempt(**a) for a in req.attempts],
        finished_at=datetime.now().isoformat(),
    )
    avg, summary = examiner.summarize_session(sess.attempts)
    sess.overall_score = avg
    append_exercise(sess)
    append_trajectory(TrajectoryEntry(node_id=req.node_id, kind="test",
                                      content=summary, meta={"score": avg}))
    p = _plan_or_404()
    p.state = "advancing" if avg >= 0.8 else "studying"
    save_plan(p)
    return {"overall_score": avg, "summary": summary, "state": p.state}


@app.post("/api/advance")
async def post_advance():
    p = _plan_or_404()
    if not p.current_node_id:
        raise HTTPException(400, "no current node")
    cur = p.current_node_id
    orchestrator.mark_node_completed(p, cur)
    completed_stage = orchestrator.stage_just_completed(p, cur)
    new_id = orchestrator.advance_to_next(p)
    append_trajectory(TrajectoryEntry(node_id=cur, kind="advance",
                                      content=f"completed; next={new_id}"))
    review_info = None
    if completed_stage:
        from . import reviewer
        try:
            target = await asyncio.to_thread(reviewer.stage_review, p, completed_stage.id)
            review_info = {"stage_id": completed_stage.id,
                           "stage_name": completed_stage.name,
                           "review_path": str(target)}
            append_trajectory(TrajectoryEntry(
                node_id=cur, kind="review",
                content=f"stage {completed_stage.id} auto-review: {target.name}",
            ))
        except Exception as e:
            review_info = {"stage_id": completed_stage.id,
                           "stage_name": completed_stage.name,
                           "error": f"{type(e).__name__}: {e}"}
    return {"completed": cur, "next": new_id, "plan": p.model_dump(),
            "stage_review": review_info}


class ArchiveReq(BaseModel):
    node_id: Optional[str] = None
    all_completed: bool = False
    all_active: bool = False


@app.post("/api/archive")
async def post_archive(req: ArchiveReq):
    p = _plan_or_404()
    if req.all_completed:
        targets = await asyncio.to_thread(archivist.archive_all, p, True)
    elif req.all_active:
        targets = await asyncio.to_thread(archivist.archive_all, p, False)
    else:
        nid = req.node_id or p.current_node_id
        n = p.find_node(nid)
        if not n:
            raise HTTPException(404, f"node {nid} not found")
        s = p.stage_of(n.id)
        target = await asyncio.to_thread(archivist.archive_node, n, s.name if s else "")
        targets = [target]
    idx = await asyncio.to_thread(archivist.build_index, p)
    return {"files": [str(t) for t in targets], "index": str(idx)}


@app.get("/api/kb")
def get_kb_index():
    p = _plan_or_404()
    idx = workspace_path("library", "notes", "INDEX.md")
    if not idx.exists():
        return {"markdown": "(no KB yet — run archive first)"}
    return {"markdown": idx.read_text(encoding="utf-8")}


@app.get("/api/kb/{node_id}")
def get_kb_node(node_id: str):
    p = _plan_or_404()
    n = p.find_node(node_id)
    if not n:
        raise HTTPException(404, f"node {node_id} not found")
    target = workspace_path("library", "notes", f"{n.id}_{_slugify(n.name)}.md")
    if not target.exists():
        return {"markdown": f"(no KB entry for {node_id} yet — POST /api/archive first)"}
    return {"markdown": target.read_text(encoding="utf-8")}


@app.post("/api/review/weekly")
async def post_weekly_review():
    p = _plan_or_404()
    target = await asyncio.to_thread(reviewer.weekly_review, p)
    return {"file": str(target), "markdown": target.read_text(encoding="utf-8")}


@app.get("/api/trajectory")
def get_trajectory(node_id: Optional[str] = None, limit: int = 50):
    return {"entries": [e.model_dump() for e in load_trajectory(node_id=node_id, limit=limit)]}


@app.get("/api/stats")
def get_stats():
    p = load_plan()
    if not p:
        return {"empty": True}
    nodes = p.all_nodes()
    done = sum(1 for n in nodes if n.status == "completed")
    # heatmap: hours per day for last 53 weeks (we only track logs as trajectory)
    all_traj = load_trajectory(limit=100000)
    by_day: dict[str, int] = {}
    for e in all_traj:
        d = e.ts[:10]
        by_day[d] = by_day.get(d, 0) + 1
    # streak
    from datetime import date as _date
    today = _date.today()
    streak = 0
    for i in range(0, 365):
        d = (today - timedelta(days=i)).isoformat()
        if by_day.get(d, 0) > 0:
            streak += 1
        elif i > 0:
            break
    # exercise scores trend
    exes = load_exercises()
    scores = [{"date": s.started_at[:10], "node": s.node_id,
               "score": s.overall_score} for s in exes if s.overall_score is not None]
    return {
        "total_nodes": len(nodes), "done_nodes": done,
        "by_day": by_day, "streak": streak, "scores": scores,
        "current_node_id": p.current_node_id, "state": p.state,
        "provider": provider_info(),
    }


# ---------- Web UI ----------

_STATIC_DIR = Path(__file__).resolve().parent / "static"


def _read_index_html() -> str:
    """Reload from disk on every request — keeps dev iteration fast and
    avoids stale content when the launchd-managed serve survives an upgrade."""
    p = _STATIC_DIR / "index.html"
    return p.read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def index():
    return _read_index_html()
