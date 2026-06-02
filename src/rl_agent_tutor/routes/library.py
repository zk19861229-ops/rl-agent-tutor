"""Resource and local-library search API routes."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import indexer, rag
from ..services import evidence as evidence_service
from ..services import learning as learning_service
from ..services import resources as resources_service


router = APIRouter()


class QueryReq(BaseModel):
    query: str
    top_n: int = 5
    rerank: bool = True


class SourcesReq(BaseModel):
    sources: list[dict]


@router.post("/api/index")
async def post_index():
    n_pdfs, n_chunks = await asyncio.to_thread(indexer.index_papers)
    return {"n_pdfs": n_pdfs, "n_chunks": n_chunks, "stats": indexer.index_stats()}


@router.get("/api/index/stats")
def get_index_stats():
    return indexer.index_stats()


@router.post("/api/query")
async def post_query(req: QueryReq):
    hits = await asyncio.to_thread(
        rag.retrieve,
        req.query,
        top_n=req.top_n,
        rerank=req.rerank,
    )
    return {
        "hits": [
            {
                "chunk_id": h.chunk.chunk_id,
                "doc_id": h.chunk.doc_id,
                "title": h.chunk.title,
                "section": h.chunk.section,
                "page": h.chunk.page,
                "score": round(h.score, 3),
                "preview": h.chunk.text[:600],
            }
            for h in hits
        ]
    }


@router.post("/api/fetch")
async def post_fetch():
    try:
        result = await asyncio.to_thread(resources_service.fetch_for_current_node)
    except learning_service.PlanNotFoundError:
        raise HTTPException(404, "No plan yet. Create one via POST /api/plan.")
    except learning_service.NoCurrentNodeError as e:
        raise HTTPException(400, str(e))
    return {"resources": [r.model_dump() for r in result.resources]}


@router.get("/api/resources/{node_id}")
def get_resources(node_id: str):
    return {
        "resources": [r.model_dump() for r in resources_service.list_node_resources(node_id)],
        "evidence": evidence_service.summarize_node(node_id).to_dict(),
    }


@router.get("/api/sources")
def get_sources():
    return {"sources": resources_service.list_sources()}


@router.put("/api/sources")
def put_sources(req: SourcesReq):
    try:
        sources = resources_service.save_sources_from_payload(req.sources)
    except Exception as exc:
        raise HTTPException(400, f"invalid sources: {exc}")
    return {"sources": sources}
