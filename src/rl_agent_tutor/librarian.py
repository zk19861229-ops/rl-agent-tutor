"""Librarian Agent — fetch learning resources for a node from multiple sources.

Pipeline for one node:
1) Ask LLM for: arxiv queries, GitHub repos, blog URLs, YouTube URLs/IDs
2) For arxiv:    use `arxiv` lib to search + download top-1 PDF
3) For GitHub:   `git clone --depth 1` into library/code/
4) For blogs:    httpx + BeautifulSoup main-text extraction → library/notes/blogs/
5) For YouTube:  youtube-transcript-api → library/notes/transcripts/
6) Persist all results to resources.jsonl
"""
from __future__ import annotations
import os
import re
import shutil
import subprocess
from pathlib import Path
import arxiv
import httpx
from .models import LearningNode, Resource
from .sources import SourceRegistry, load_source_registry
from .sources.pipeline import run_source_providers
from .sources.planner import plan_source_fetches
from .utils import slugify
from .fetchers import (
    fetch_blog, save_blog_md,
    fetch_youtube_transcript, save_youtube_md, youtube_id,
)


def _slugify(s: str, n: int = 60) -> str:
    return slugify(s, n=n, allow_dot=True)


_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def _validate_github_repo(repo: str) -> tuple[str, str] | None:
    """Validate `owner/name` shape and reject path-traversal-ish tokens.

    Rejects names starting with '.', containing '..', or '/' beyond the single
    separator — anything the LLM might hallucinate that could escape code_dir.
    """
    repo = (repo or "").strip()
    if not _REPO_RE.match(repo):
        return None
    owner, name = repo.split("/", 1)
    if name in (".", "..") or name.startswith("."):
        return None
    if ".." in name or ".." in owner:
        return None
    return owner, name


# ---------- arxiv ----------

def fetch_arxiv_paper(query: str, node_id: str, papers_dir: Path) -> Resource | None:
    try:
        search = arxiv.Search(query=query, max_results=1, sort_by=arxiv.SortCriterion.Relevance)
        # arxiv >= 2.0 deprecates Search.results() in favor of Client().results(search)
        try:
            client = arxiv.Client()
            results = list(client.results(search))
        except (AttributeError, TypeError):
            results = list(search.results())
    except Exception as e:
        return Resource(
            node_id=node_id, kind="paper",
            title=f"[search failed: {query}]", url=None,
            summary=f"arxiv search error: {e}",
        )
    if not results:
        return None
    paper = results[0]
    arxiv_id = paper.entry_id.rsplit("/", 1)[-1]
    safe = _slugify(paper.title, 50)
    fname = f"{arxiv_id}_{safe}.pdf"
    target = papers_dir / fname
    if not target.exists():
        try:
            # arxiv >= 2.0: download_pdf moved off Result; new API: use httpx fallback
            if hasattr(paper, "download_pdf"):
                paper.download_pdf(dirpath=str(papers_dir), filename=fname)
            else:
                # manual fallback — fetch pdf_url ourselves
                pdf_url = getattr(paper, "pdf_url", None) or paper.entry_id.replace("/abs/", "/pdf/")
                if not pdf_url.endswith(".pdf"):
                    pdf_url += ".pdf"
                with httpx.Client(follow_redirects=True, timeout=60.0) as c:
                    resp = c.get(pdf_url)
                    resp.raise_for_status()
                    target.write_bytes(resp.content)
        except Exception as e:
            return Resource(
                node_id=node_id, kind="paper", title=paper.title,
                url=paper.entry_id, summary=f"download failed: {e}",
            )
    return Resource(
        node_id=node_id, kind="paper",
        title=paper.title,
        url=paper.entry_id,
        local_path=str(target),
        summary=(paper.summary or "")[:500],
    )


# ---------- github ----------

def clone_github_repo(repo: str, node_id: str, code_dir: Path) -> Resource | None:
    parts = _validate_github_repo(repo)
    if not parts:
        return Resource(node_id=node_id, kind="code", title=str(repo)[:200],
                        url=None,
                        summary=f"rejected repo name: {repo!r} (invalid shape)")
    owner, name = parts
    repo = f"{owner}/{name}"

    code_dir_abs = code_dir.resolve()
    target = (code_dir / name).resolve()
    try:
        target.relative_to(code_dir_abs)
    except ValueError:
        return Resource(node_id=node_id, kind="code", title=repo,
                        url=f"https://github.com/{repo}",
                        summary="path traversal blocked")

    if target.exists():
        return Resource(node_id=node_id, kind="code", title=repo,
                        url=f"https://github.com/{repo}",
                        local_path=str(target), summary="(already cloned)")
    if shutil.which("git") is None:
        return Resource(node_id=node_id, kind="code", title=repo,
                        url=f"https://github.com/{repo}",
                        summary="git not installed; clone manually")
    url = f"https://github.com/{repo}.git"
    # Isolate: skip user/system git config so a hostile clone can't trigger
    # post-checkout hooks or include directives, and force HTTPS so url isn't
    # rewritten via insteadOf.
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_ASKPASS": "true",
    }
    try:
        subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null",
             "-c", "protocol.allow=user",
             "-c", "http.followRedirects=false",
             "clone", "--depth", "1", "--no-tags",
             "--config", "core.hooksPath=/dev/null",
             url, str(target)],
            check=True, capture_output=True, timeout=120, env=env,
        )
    except Exception as e:
        return Resource(node_id=node_id, kind="code", title=repo,
                        url=f"https://github.com/{repo}",
                        summary=f"clone failed: {e}")
    return Resource(node_id=node_id, kind="code", title=repo,
                    url=f"https://github.com/{repo}", local_path=str(target),
                    summary="cloned successfully")


# ---------- blogs ----------

def fetch_blog_resource(url: str, why: str, node_id: str, blogs_dir: Path) -> Resource | None:
    blog = fetch_blog(url)
    if blog.get("error"):
        return Resource(node_id=node_id, kind="blog", title=url,
                        url=url, summary=f"fetch failed: {blog['error']}")
    if not blog.get("text"):
        return Resource(node_id=node_id, kind="blog", title=blog.get("title", url),
                        url=url, summary="empty content extracted")
    target = save_blog_md(blog, blogs_dir, slug_hint=_slugify(blog.get("title", ""), 50))
    summary = (why + " · " if why else "") + blog["text"][:300].replace("\n", " ")
    return Resource(node_id=node_id, kind="blog", title=blog.get("title", url),
                    url=url, local_path=str(target), summary=summary)


# ---------- youtube ----------

def fetch_youtube_resource(url_or_id: str, title: str, why: str,
                           node_id: str, transcripts_dir: Path) -> Resource | None:
    yt = fetch_youtube_transcript(url_or_id)
    vid = yt.get("video_id") or youtube_id(url_or_id) or url_or_id
    canonical_url = f"https://www.youtube.com/watch?v={vid}" if vid else url_or_id
    if yt.get("error"):
        return Resource(node_id=node_id, kind="video", title=title or vid,
                        url=canonical_url, summary=f"transcript unavailable: {yt['error']}")
    target = save_youtube_md(yt, transcripts_dir, title=title)
    summary = (why + " · " if why else "") + yt.get("text", "")[:300].replace("\n", " ")
    return Resource(node_id=node_id, kind="video", title=title or vid,
                    url=canonical_url, local_path=str(target), summary=summary)


# ---------- main entry ----------

def fetch_for_node(node: LearningNode, registry: SourceRegistry | None = None) -> list[Resource]:
    registry = registry or load_source_registry()
    plan_json = plan_source_fetches(node, registry)
    return run_source_providers(node, registry, plan_json)
