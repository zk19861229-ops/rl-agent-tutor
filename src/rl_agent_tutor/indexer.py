"""Indexer — extract text from PDFs, split into section-aware chunks, build BM25 index.

Pipeline per PDF:
1) pymupdf opens it, walks every page → blocks → text
2) Use the PDF outline (TOC) when available to bound sections
3) Fallback: regex-based section header detection ("3. Method", "## Method", etc.)
4) Each section becomes a chunk (further split if > MAX_CHARS)
5) Chunks persist to library/index/chunks.jsonl with metadata
6) BM25 index is rebuilt over all chunks (cached as a pickle)

Tokenization: regex word-split for English + jieba for CJK. The same tokenizer is
used at index and query time.
"""
from __future__ import annotations
import json
import os
import pickle
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Optional

from .config import workspace_path


MAX_CHARS = 3500          # max chars per chunk before splitting further
MIN_CHARS = 200           # discard tiny scraps
OVERLAP_CHARS = 200       # context overlap when splitting long sections


# ---------- Tokenization ----------

_word_re = re.compile(r"[A-Za-z0-9_]+")
_cjk_re = re.compile(r"[一-鿿]+")
_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "is", "are", "and", "or", "for", "on",
    "with", "as", "by", "we", "this", "that", "be", "it", "from", "at",
    "其", "的", "了", "和", "在", "是", "也", "等", "及", "与", "对",
}


def tokenize(text: str) -> list[str]:
    """Lowercase + word/CJK tokenization. Lazy import jieba so cold start is fast."""
    text = text.lower()
    out = _word_re.findall(text)
    cjk_chunks = _cjk_re.findall(text)
    if cjk_chunks:
        try:
            import jieba
            for blob in cjk_chunks:
                out.extend(t for t in jieba.lcut(blob) if t.strip())
        except ImportError:
            # fallback: per-char
            for blob in cjk_chunks:
                out.extend(list(blob))
    return [t for t in out if t and t not in _STOPWORDS and len(t) > 1]


# ---------- Chunk ----------

@dataclass
class Chunk:
    chunk_id: str             # "<doc_stem>::<section_idx>::<part_idx>"
    doc_id: str               # filename stem, e.g. "1707.06347_PPO"
    doc_path: str             # absolute path
    title: str                # PDF title or filename
    section: str              # section heading
    page: int                 # first page of this chunk (1-indexed)
    text: str

    @classmethod
    def from_dict(cls, d: dict) -> "Chunk":
        return cls(**d)


# ---------- PDF parsing ----------

_section_header_re = re.compile(
    r"^(?:"
    r"\d+(?:\.\d+){0,3}\s+[A-Z][A-Za-z0-9 ,\-:&/]+"
    r"|"
    r"(?:Abstract|Introduction|Background|Related Work|Method(?:ology)?|"
    r"Approach|Experiments?|Results?|Discussion|Conclusions?|"
    r"References|Appendix|Algorithm)\b.*"
    r")\s*$",
    re.MULTILINE,
)


def _extract_pages(pdf_path: Path) -> list[tuple[int, str]]:
    """Return [(page_no_1indexed, full_page_text), ...]."""
    try:
        import fitz  # pymupdf
    except ImportError:
        raise RuntimeError("pymupdf not installed. pip install pymupdf")
    out: list[tuple[int, str]] = []
    with fitz.open(pdf_path) as doc:
        for i, page in enumerate(doc, start=1):
            try:
                txt = page.get_text("text")
            except Exception:
                txt = ""
            out.append((i, txt or ""))
    return out


def _doc_title(pdf_path: Path) -> str:
    """Try metadata title, else first H1-ish line, else filename stem."""
    try:
        import fitz
        with fitz.open(pdf_path) as doc:
            t = (doc.metadata or {}).get("title") or ""
            t = t.strip()
            if t and len(t) > 5 and not t.lower().startswith("untitled"):
                return t
    except Exception:
        pass
    return pdf_path.stem.replace("_", " ")


def _toc_sections(pdf_path: Path) -> list[tuple[str, int]]:
    """Return [(section_title, start_page), ...] from PDF outline if present."""
    try:
        import fitz
        with fitz.open(pdf_path) as doc:
            toc = doc.get_toc(simple=True)  # [[level, title, page], ...]
    except Exception:
        return []
    out = []
    for entry in toc or []:
        if len(entry) >= 3:
            level, title, page = entry[0], entry[1], entry[2]
            if level <= 2 and isinstance(page, int) and page > 0:
                out.append((title.strip(), page))
    return out


def _split_by_regex(pages: list[tuple[int, str]]) -> list[tuple[str, int, str]]:
    """Heuristic section detection when no TOC. Returns [(title, page, body), ...]."""
    full = "\n".join(f"\f§PAGE{p}§\n{t}" for p, t in pages)
    sections: list[tuple[str, int, str]] = []
    last_pos = 0
    last_title = "Front matter"
    last_page = 1

    def page_at(pos: int) -> int:
        # look back for last §PAGE marker
        m = list(re.finditer(r"§PAGE(\d+)§", full[:pos]))
        return int(m[-1].group(1)) if m else 1

    for m in _section_header_re.finditer(full):
        body = full[last_pos:m.start()]
        body = re.sub(r"§PAGE\d+§", "", body).strip()
        if body:
            sections.append((last_title, last_page, body))
        last_title = m.group(0).strip()
        last_pos = m.end()
        last_page = page_at(m.start())
    tail = re.sub(r"§PAGE\d+§", "", full[last_pos:]).strip()
    if tail:
        sections.append((last_title, last_page, tail))
    return sections


def _split_by_toc(pages: list[tuple[int, str]],
                  toc: list[tuple[str, int]]) -> list[tuple[str, int, str]]:
    """Use TOC page boundaries to define sections."""
    sections = []
    page_text = {p: t for p, t in pages}
    bounded = list(toc) + [("__END__", len(pages) + 1)]
    for i in range(len(bounded) - 1):
        title, start = bounded[i]
        _, end = bounded[i + 1]
        body = "\n".join(page_text.get(p, "") for p in range(start, end))
        body = body.strip()
        if body:
            sections.append((title, start, body))
    return sections


def _split_long(text: str) -> list[str]:
    """Split a too-long section on paragraph boundaries with small overlap."""
    if len(text) <= MAX_CHARS:
        return [text]
    paras = text.split("\n\n")
    out, cur = [], ""
    for p in paras:
        if len(cur) + len(p) + 2 <= MAX_CHARS:
            cur = (cur + "\n\n" + p) if cur else p
        else:
            if cur:
                out.append(cur)
            # carry a tail of the previous chunk for context
            tail = cur[-OVERLAP_CHARS:] if cur else ""
            cur = (tail + "\n\n" + p).strip() if tail else p
    if cur:
        out.append(cur)
    return out


def chunk_pdf(pdf_path: Path) -> list[Chunk]:
    pages = _extract_pages(pdf_path)
    title = _doc_title(pdf_path)
    toc = _toc_sections(pdf_path)
    sections = _split_by_toc(pages, toc) if toc else _split_by_regex(pages)

    chunks: list[Chunk] = []
    doc_id = pdf_path.stem
    for s_idx, (sec_title, page, body) in enumerate(sections):
        body = re.sub(r"\s+\n", "\n", body).strip()
        if len(body) < MIN_CHARS:
            continue
        for p_idx, part in enumerate(_split_long(body)):
            if len(part) < MIN_CHARS:
                continue
            chunks.append(Chunk(
                chunk_id=f"{doc_id}::{s_idx}::{p_idx}",
                doc_id=doc_id,
                doc_path=str(pdf_path),
                title=title,
                section=sec_title,
                page=page,
                text=part,
            ))
    return chunks


# ---------- Persistence + BM25 ----------

def chunks_path() -> Path:
    return workspace_path("library", "index", "chunks.jsonl")


def bm25_path() -> Path:
    return workspace_path("library", "index", "bm25.pkl")


def _mtime_cache_path() -> Path:
    return workspace_path("library", "index", "mtime.json")


def _load_mtime_cache() -> dict[str, float]:
    p = _mtime_cache_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_mtime_cache(cache: dict[str, float]) -> None:
    p = _mtime_cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _save_chunks(all_chunks: list[Chunk]) -> None:
    target = chunks_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for c in all_chunks:
            f.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, target)


def load_chunks() -> list[Chunk]:
    target = chunks_path()
    if not target.exists():
        return []
    out = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(Chunk.from_dict(json.loads(line)))
    return out


def _build_bm25(chunks: list[Chunk]):
    from rank_bm25 import BM25Okapi
    corpus = [tokenize(c.text) for c in chunks]
    bm25 = BM25Okapi(corpus) if corpus else None
    target = bm25_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("wb") as f:
        pickle.dump({"bm25": bm25, "ids": [c.chunk_id for c in chunks]}, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, target)


def load_bm25():
    """Return (bm25_object, [chunk_ids]) or (None, [])."""
    p = bm25_path()
    if not p.exists():
        return None, []
    with p.open("rb") as f:
        data = pickle.load(f)
    return data.get("bm25"), data.get("ids", [])


# ---------- Public API ----------

def index_papers(papers_dir: Optional[Path] = None,
                 progress=None,
                 force: bool = False) -> tuple[int, int, list[tuple[str, str]]]:
    """Reindex PDFs under workspace/library/papers/.

    Returns (n_pdfs, n_chunks, failures) where failures is a list of
    (pdf_filename, error_message) for PDFs that couldn't be parsed. The CLI
    forwards failures to the trajectory so they're not just swallowed by stdout.

    Incremental: PDFs whose mtime hasn't changed since last index reuse cached
    chunks. Pass force=True to rebuild everything.
    """
    papers_dir = papers_dir or workspace_path("library", "papers")
    papers_dir.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(papers_dir.glob("*.pdf"))

    mtime_cache = {} if force else _load_mtime_cache()
    cached_chunks = [] if force else load_chunks()
    chunks_by_doc: dict[str, list[Chunk]] = {}
    for c in cached_chunks:
        chunks_by_doc.setdefault(c.doc_id, []).append(c)

    new_cache: dict[str, float] = {}
    all_chunks: list[Chunk] = []
    current_doc_ids: set[str] = set()
    failures: list[tuple[str, str]] = []

    for pdf in pdfs:
        doc_id = pdf.stem
        current_doc_ids.add(doc_id)
        mtime = pdf.stat().st_mtime
        new_cache[doc_id] = mtime
        if (not force
                and mtime_cache.get(doc_id) == mtime
                and doc_id in chunks_by_doc):
            all_chunks.extend(chunks_by_doc[doc_id])
            continue
        if progress:
            progress(pdf.name)
        try:
            all_chunks.extend(chunk_pdf(pdf))
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            print(f"[indexer] failed on {pdf.name}: {err}")
            failures.append((pdf.name, err))
            # keep stale chunks if rechunk failed, so users don't lose hits
            if doc_id in chunks_by_doc:
                all_chunks.extend(chunks_by_doc[doc_id])
                new_cache[doc_id] = mtime_cache.get(doc_id, 0)

    _save_chunks(all_chunks)
    _build_bm25(all_chunks)
    _save_mtime_cache(new_cache)
    return len(pdfs), len(all_chunks), failures


def index_stats() -> dict:
    chunks = load_chunks()
    docs = sorted({c.doc_id for c in chunks})
    return {
        "n_documents": len(docs),
        "n_chunks": len(chunks),
        "documents": docs,
    }
