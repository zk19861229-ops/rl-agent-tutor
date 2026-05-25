"""Fetchers for blog posts and YouTube transcripts.

Blog: lightweight HTML → main text extraction using BeautifulSoup heuristics
(no readability lib needed for MVP — we just pick the densest <article>/<main>/<body> chunk).

YouTube: youtube-transcript-api pulls auto-captions or human-uploaded captions.
"""
from __future__ import annotations
import re
import urllib.parse
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 rl-agent-tutor"


# ---------- Blog ----------

def _strip(html_node) -> str:
    for tag in html_node.select("script, style, nav, footer, header, aside, form, noscript"):
        tag.decompose()
    return html_node.get_text(separator="\n", strip=True)


def _pick_main(soup: BeautifulSoup) -> str:
    for sel in ["article", "main", "[role=main]", ".post", ".entry-content", "#content"]:
        node = soup.select_one(sel)
        if node:
            txt = _strip(node)
            if len(txt) > 400:
                return txt
    body = soup.body or soup
    return _strip(body)


def fetch_blog(url: str) -> dict:
    """Return {'title':..., 'text':..., 'url':...} for a blog/article URL."""
    try:
        with httpx.Client(headers={"User-Agent": UA}, timeout=30.0, follow_redirects=True) as c:
            resp = c.get(url)
            resp.raise_for_status()
            html = resp.text
    except Exception as e:
        return {"title": "", "text": "", "url": url, "error": str(e)}

    soup = BeautifulSoup(html, "lxml")
    title_tag = soup.find("title")
    h1 = soup.find("h1")
    title = (h1.get_text(strip=True) if h1 else "") or (title_tag.get_text(strip=True) if title_tag else "")

    text = _pick_main(soup)
    # collapse blank lines
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return {"title": title or url, "text": text, "url": url}


def save_blog_md(blog: dict, target_dir: Path, slug_hint: str = "") -> Path:
    """Save a blog as a Markdown file. Returns the path."""
    target_dir.mkdir(parents=True, exist_ok=True)
    base = slug_hint or re.sub(r"[^a-zA-Z0-9_-]+", "_", blog.get("title", "blog"))[:60].lower()
    if not base:
        base = "blog"
    target = target_dir / f"{base}.md"
    i = 1
    while target.exists():
        target = target_dir / f"{base}_{i}.md"
        i += 1
    body = f"# {blog.get('title','(untitled)')}\n\nSource: {blog.get('url','')}\n\n---\n\n{blog.get('text','')}\n"
    target.write_text(body, encoding="utf-8")
    return target


# ---------- YouTube ----------

YT_ID_RE = re.compile(
    r"(?:v=|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})"
)


def youtube_id(url_or_id: str) -> Optional[str]:
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url_or_id):
        return url_or_id
    m = YT_ID_RE.search(url_or_id)
    return m.group(1) if m else None


def fetch_youtube_transcript(url_or_id: str, languages: tuple[str, ...] = ("en", "zh-Hans", "zh-Hant", "zh")) -> dict:
    """Return {'video_id', 'language', 'text', 'segments', 'url'} or {'error': ...}."""
    vid = youtube_id(url_or_id)
    if not vid:
        return {"error": f"could not parse video id from {url_or_id}"}
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # lazy import
    except ImportError:
        return {"error": "youtube-transcript-api not installed"}

    try:
        listing = YouTubeTranscriptApi.list_transcripts(vid)
    except Exception as e:
        return {"error": f"list_transcripts failed: {e}", "video_id": vid}

    transcript = None
    chosen_lang = None
    # try requested languages first
    for lang in languages:
        try:
            transcript = listing.find_transcript([lang])
            chosen_lang = lang
            break
        except Exception:
            continue
    # then any generated transcript
    if transcript is None:
        try:
            transcript = listing.find_generated_transcript(list(languages))
            chosen_lang = transcript.language_code
        except Exception:
            pass
    # then anything at all
    if transcript is None:
        try:
            for t in listing:
                transcript = t
                chosen_lang = t.language_code
                break
        except Exception:
            pass

    if transcript is None:
        return {"error": "no transcript available", "video_id": vid}

    try:
        segments = transcript.fetch()
    except Exception as e:
        return {"error": f"fetch failed: {e}", "video_id": vid}

    text = "\n".join(seg.get("text", "").strip() for seg in segments if seg.get("text"))
    return {
        "video_id": vid,
        "language": chosen_lang,
        "text": text,
        "segments": segments,
        "url": f"https://www.youtube.com/watch?v={vid}",
    }


def save_youtube_md(yt: dict, target_dir: Path, title: str = "") -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    vid = yt.get("video_id", "video")
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", title or vid)[:60].lower() or vid
    target = target_dir / f"{safe}_{vid}.md"
    body = (
        f"# {title or yt.get('video_id','YouTube Transcript')}\n\n"
        f"Source: {yt.get('url','')}\n"
        f"Language: {yt.get('language','?')}\n\n"
        f"---\n\n"
        f"{yt.get('text','')}\n"
    )
    target.write_text(body, encoding="utf-8")
    return target
