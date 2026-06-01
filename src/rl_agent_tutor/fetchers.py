"""Fetchers for blog posts and YouTube transcripts.

Blog: lightweight HTML → main text extraction using BeautifulSoup heuristics
(no readability lib needed for MVP — we just pick the densest <article>/<main>/<body> chunk).

YouTube: youtube-transcript-api pulls auto-captions or human-uploaded captions.
"""
from __future__ import annotations
import ipaddress
import re
import socket
import urllib.parse
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 rl-agent-tutor"


# ---------- SSRF guard ----------

class UnsafeURLError(ValueError):
    """Raised when a URL targets a private/loopback/link-local address."""


def _is_private_ip(ip: ipaddress._BaseAddress) -> bool:
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def _check_url_safe(url: str) -> str:
    """Validate `url` resolves only to public IPs and uses http(s).

    The LLM (Librarian) hands us URLs to fetch. Without this check, a confused
    or hallucinated URL could pull from `http://localhost`, `http://10.0.0.1`,
    or even `file://` / `gopher://`. Returns the (parsed) URL or raises
    UnsafeURLError.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(f"unsupported scheme: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("missing host")
    # If the host already is an IP literal, validate directly. Otherwise resolve.
    try:
        ip = ipaddress.ip_address(host)
        if _is_private_ip(ip):
            raise UnsafeURLError(f"refusing to fetch from {ip}")
        return url
    except ValueError:
        pass  # not an IP literal — fall through to DNS lookup
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise UnsafeURLError(f"DNS lookup failed for {host}: {e}")
    for info in infos:
        sockaddr = info[4]
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if _is_private_ip(ip):
            raise UnsafeURLError(f"refusing to fetch {host} → {ip}")
    return url


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
        _check_url_safe(url)
    except UnsafeURLError as e:
        return {"title": "", "text": "", "url": url, "error": f"unsafe URL: {e}"}
    try:
        with httpx.Client(headers={"User-Agent": UA}, timeout=30.0, follow_redirects=False) as c:
            # Manual redirect handling so we can re-validate each hop.
            current = url
            for _ in range(5):
                resp = c.get(current)
                if resp.is_redirect:
                    nxt = resp.headers.get("location", "")
                    if not nxt:
                        return {"title": "", "text": "", "url": url, "error": "empty redirect"}
                    nxt = urllib.parse.urljoin(current, nxt)
                    _check_url_safe(nxt)
                    current = nxt
                    continue
                resp.raise_for_status()
                html = resp.text
                break
            else:
                return {"title": "", "text": "", "url": url, "error": "too many redirects"}
    except UnsafeURLError as e:
        return {"title": "", "text": "", "url": url, "error": f"unsafe redirect: {e}"}
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

    text = "\n".join(_seg_text(seg) for seg in segments if _seg_text(seg))
    return {
        "video_id": vid,
        "language": chosen_lang,
        "text": text,
        "segments": [_seg_to_dict(s) for s in segments],
        "url": f"https://www.youtube.com/watch?v={vid}",
    }


def _seg_text(seg) -> str:
    """Pull `text` from either a dict or a youtube-transcript-api dataclass."""
    if isinstance(seg, dict):
        return (seg.get("text") or "").strip()
    return (getattr(seg, "text", "") or "").strip()


def _seg_to_dict(seg) -> dict:
    if isinstance(seg, dict):
        return seg
    return {
        "text": getattr(seg, "text", ""),
        "start": getattr(seg, "start", None),
        "duration": getattr(seg, "duration", None),
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
