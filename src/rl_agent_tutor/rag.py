"""RAG — retrieve relevant chunks from the local PDF index, optionally LLM-rerank, return citations.

Pipeline:
1) tokenize query (same tokenizer as indexer)
2) BM25 score → top-K candidates
3) Optional: LLM rerank top-K → top-N (for high-quality answers)
4) Return chunks with citation metadata for the caller to inject into prompts
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Optional

from .indexer import load_bm25, load_chunks, tokenize, Chunk
from .llm import chat_json


@dataclass
class Hit:
    chunk: Chunk
    score: float

    def citation(self) -> str:
        c = self.chunk
        return f"[{c.doc_id} · §{c.section} · p.{c.page}]"

    def as_context_block(self) -> str:
        return (
            f"--- CITATION {self.citation()} ---\n"
            f"Title: {self.chunk.title}\n"
            f"Section: {self.chunk.section}\n"
            f"{self.chunk.text}\n"
        )


# ---------- BM25 retrieval ----------

def bm25_search(query: str, top_k: int = 12,
                doc_filter: Optional[list[str]] = None) -> list[Hit]:
    bm25, ids = load_bm25()
    if bm25 is None or not ids:
        return []
    chunks = {c.chunk_id: c for c in load_chunks()}
    scores = bm25.get_scores(tokenize(query))
    pairs = list(zip(ids, scores))
    if doc_filter:
        pairs = [p for p in pairs if chunks.get(p[0]) and chunks[p[0]].doc_id in doc_filter]
    pairs.sort(key=lambda x: x[1], reverse=True)
    out: list[Hit] = []
    for cid, sc in pairs[:top_k]:
        c = chunks.get(cid)
        if c and sc > 0:
            out.append(Hit(chunk=c, score=float(sc)))
    return out


# ---------- LLM rerank ----------

RERANK_SYSTEM = """You rerank retrieved passages for relevance to a learner's question.
You will see the question and candidate passages (with citation IDs). Pick the IDs most
likely to contain the actual answer (not just topic-related). Be ruthless — return only
the strongest matches. Order matters: first = most relevant."""

RERANK_USER_TPL = """Question: {q}

Candidate passages (cite by chunk_id):
{cands}

Return JSON:
{{ "ranked_ids": ["<chunk_id1>", "<chunk_id2>", ...] }}

Include at most {n} ids. Prefer passages that *answer* the question.
Output JSON only."""


def llm_rerank(query: str, hits: list[Hit], top_n: int = 5) -> list[Hit]:
    if not hits:
        return hits
    if len(hits) <= top_n:
        return hits
    cands = "\n\n".join(
        f"[{h.chunk.chunk_id}] §{h.chunk.section} (p.{h.chunk.page}): "
        f"{h.chunk.text[:400].replace(chr(10),' ')}…"
        for h in hits
    )
    try:
        out = chat_json(
            RERANK_SYSTEM,
            RERANK_USER_TPL.format(q=query, cands=cands, n=top_n),
            max_tokens=600,
        )
        ranked = out.get("ranked_ids", [])
    except Exception:
        return hits[:top_n]
    by_id = {h.chunk.chunk_id: h for h in hits}
    out_hits = [by_id[i] for i in ranked if i in by_id]
    if len(out_hits) < top_n:
        seen = {h.chunk.chunk_id for h in out_hits}
        for h in hits:
            if h.chunk.chunk_id not in seen:
                out_hits.append(h)
                if len(out_hits) >= top_n:
                    break
    return out_hits[:top_n]


# ---------- Public ----------

def retrieve(query: str, *, top_k_bm25: int = 12, top_n: int = 5,
             rerank: bool = True,
             doc_filter: Optional[list[str]] = None) -> list[Hit]:
    """Main entry: BM25 → optional LLM rerank → top-N."""
    hits = bm25_search(query, top_k=top_k_bm25, doc_filter=doc_filter)
    if rerank and hits:
        hits = llm_rerank(query, hits, top_n=top_n)
    return hits[:top_n]


def render_context(hits: list[Hit], *, max_chars: int = 8000) -> tuple[str, list[dict]]:
    """Render a context block for prompt injection. Returns (text, citations)."""
    if not hits:
        return "", []
    blocks, used = [], []
    total = 0
    for h in hits:
        block = h.as_context_block()
        if total + len(block) > max_chars and blocks:
            break
        blocks.append(block)
        used.append({
            "chunk_id": h.chunk.chunk_id,
            "doc_id": h.chunk.doc_id,
            "title": h.chunk.title,
            "section": h.chunk.section,
            "page": h.chunk.page,
            "score": round(h.score, 3),
            "preview": h.chunk.text[:200].replace("\n", " "),
        })
        total += len(block)
    return "\n\n".join(blocks), used


def with_rag(query: str, *, top_n: int = 5, max_chars: int = 8000,
             rerank: bool = True,
             doc_filter: Optional[list[str]] = None) -> tuple[str, list[dict], list[Hit]]:
    """One-shot retrieval+render used by tutor/examiner/archivist.

    Returns (context_text, citations, hits). All callers want the same
    retrieve→render pair, so collapse it here. context_text is "" when there's
    no index or no hit — caller decides whether to skip injection.
    """
    hits = retrieve(query, top_n=top_n, rerank=rerank, doc_filter=doc_filter)
    if not hits:
        return "", [], []
    text, citations = render_context(hits, max_chars=max_chars)
    return text, citations, hits
