"""Built-in provider implementations.

These classes keep source-specific policy out of `librarian.fetch_for_node`.
They call the existing low-level fetch helpers so behavior stays compatible.
"""
from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree

import httpx

from ...models import LearningNode, Resource
from ...utils import slugify
from ..models import SourceFetchResult
from .base import SourceProvider


class ArxivProvider(SourceProvider):
    def fetch(self, node: LearningNode, plan_json: dict, dirs: dict[str, Path]) -> SourceFetchResult:
        from ... import librarian

        queries = list(self.source.config.get("queries") or [])
        query = self.source.config.get("query")
        if query:
            queries.append(str(query))
        queries.extend(plan_json.get("arxiv_queries", []))

        resources: list[Resource] = []
        for query_text in _dedupe(queries)[:4]:
            resource = librarian.fetch_arxiv_paper(str(query_text), node.id, dirs["papers"])
            if resource:
                resources.append(self.tag(resource))
        return _result(self.source.id, resources)


class GithubProvider(SourceProvider):
    def fetch(self, node: LearningNode, plan_json: dict, dirs: dict[str, Path]) -> SourceFetchResult:
        from ... import librarian

        repos = list(self.source.config.get("repos") or [])
        repo = self.source.config.get("repo")
        if repo:
            repos.append(str(repo))
        repos.extend(plan_json.get("github_repos", []))

        if self.source.type == "github_allowlist":
            allowlist = set(str(item).strip() for item in self.source.config.get("allowlist", []) or [])
            if self.source.config.get("repo"):
                allowlist.add(str(self.source.config["repo"]).strip())
            if allowlist:
                repos = [item for item in repos if str(item).strip() in allowlist]

        resources: list[Resource] = []
        for repo_name in _dedupe(repos)[:4]:
            resource = librarian.clone_github_repo(str(repo_name), node.id, dirs["code"])
            if resource:
                resources.append(self.tag(resource))
        return _result(self.source.id, resources)


class WebsiteProvider(SourceProvider):
    def fetch(self, node: LearningNode, plan_json: dict, dirs: dict[str, Path]) -> SourceFetchResult:
        from ... import librarian

        items = []
        configured = self.source.config.get("urls") or []
        for url in configured:
            items.append({"url": url, "why": self.source.name})
        if self.source.config.get("url"):
            items.append({"url": self.source.config["url"], "why": self.source.name})
        items.extend(plan_json.get("blog_urls", []))

        resources: list[Resource] = []
        for item in items[:4]:
            url = item.get("url") if isinstance(item, dict) else item
            why = item.get("why", "") if isinstance(item, dict) else ""
            if not url:
                continue
            resource = librarian.fetch_blog_resource(str(url), str(why), node.id, dirs["blogs"])
            if resource:
                resources.append(self.tag(resource))
        return _result(self.source.id, resources)


class RssProvider(SourceProvider):
    def fetch(self, node: LearningNode, plan_json: dict, dirs: dict[str, Path]) -> SourceFetchResult:
        from ... import librarian

        feed_url = str(self.source.config.get("url") or self.source.config.get("feed_url") or "")
        if not feed_url:
            return SourceFetchResult(source_id=self.source.id, error="rss source missing url")
        try:
            with httpx.Client(follow_redirects=True, timeout=20.0) as client:
                response = client.get(feed_url)
                response.raise_for_status()
            urls = _rss_links(response.text)
        except Exception as exc:
            return SourceFetchResult(source_id=self.source.id, error=str(exc))

        resources: list[Resource] = []
        for url in urls[:3]:
            resource = librarian.fetch_blog_resource(url, f"RSS: {self.source.name}", node.id, dirs["blogs"])
            if resource:
                resources.append(self.tag(resource))
        return _result(self.source.id, resources)


class YoutubeProvider(SourceProvider):
    def fetch(self, node: LearningNode, plan_json: dict, dirs: dict[str, Path]) -> SourceFetchResult:
        from ... import librarian

        items = []
        feed_error = ""
        if self.source.type in {"youtube_playlist", "youtube_channel"}:
            try:
                for url in _youtube_feed_links(self.source)[:3]:
                    items.append({"url_or_id": url, "title": self.source.name, "why": f"{self.source.type} feed"})
            except Exception as exc:
                feed_error = str(exc)
        for url in self.source.config.get("videos", []) or []:
            items.append({"url_or_id": url, "title": self.source.name, "why": "configured video"})
        if self.source.config.get("url"):
            items.append({"url_or_id": self.source.config["url"], "title": self.source.name, "why": "configured video"})
        items.extend(plan_json.get("youtube_videos", []))

        resources: list[Resource] = []
        for item in items[:3]:
            if isinstance(item, dict):
                ref = item.get("url_or_id") or item.get("url") or item.get("id")
                title = item.get("title", "")
                why = item.get("why", "")
            else:
                ref = item
                title = ""
                why = ""
            if not ref:
                continue
            resource = librarian.fetch_youtube_resource(str(ref), str(title), str(why), node.id, dirs["transcripts"])
            if resource:
                resources.append(self.tag(resource))
        result = _result(self.source.id, resources)
        result.error = feed_error
        return result


class LocalDirectoryProvider(SourceProvider):
    def fetch(self, node: LearningNode, plan_json: dict, dirs: dict[str, Path]) -> SourceFetchResult:
        base = Path(str(self.source.config.get("path") or "")).expanduser()
        if not base:
            return SourceFetchResult(source_id=self.source.id, error="local_directory missing path")
        if not base.is_absolute():
            base = dirs["workspace"] / base
        if not base.exists() or not base.is_dir():
            return SourceFetchResult(source_id=self.source.id, error=f"directory not found: {base}")

        resources: list[Resource] = []
        for path in sorted(base.rglob("*")):
            if len(resources) >= 8:
                break
            if not path.is_file() or path.name.startswith("."):
                continue
            kind = _kind_for_path(path)
            if not kind:
                continue
            resources.append(
                self.tag(
                    Resource(
                        node_id=node.id,
                        kind=kind,
                        title=path.stem.replace("_", " ").replace("-", " "),
                        local_path=str(path),
                        summary=f"Local source: {self.source.name}",
                    )
                )
            )
        return _result(self.source.id, resources)


def _result(source_id: str, resources: list[Resource]) -> SourceFetchResult:
    return SourceFetchResult(
        source_id=source_id,
        resources=resources,
        candidates=[
            {
                "source_id": resource.source_id or source_id,
                "kind": resource.kind,
                "title": resource.title,
                "url": resource.url,
                "local_path": resource.local_path,
                "priority": resource.priority,
            }
            for resource in resources
        ],
    )


def _dedupe(items: list) -> list:
    seen: set[str] = set()
    out = []
    for item in items:
        key = str(item).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _rss_links(text: str) -> list[str]:
    root = ElementTree.fromstring(text)
    links: list[str] = []
    for item in root.findall(".//item"):
        link = item.findtext("link")
        if link:
            links.append(link.strip())
    for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
        for link in entry.findall("{http://www.w3.org/2005/Atom}link"):
            href = link.attrib.get("href")
            if href:
                links.append(href.strip())
    return _dedupe(links)


def _youtube_feed_links(source) -> list[str]:
    playlist_id = source.config.get("playlist_id") or _query_param(str(source.config.get("url") or ""), "list")
    channel_id = source.config.get("channel_id") or _channel_id(str(source.config.get("url") or ""))
    if playlist_id:
        feed_url = f"https://www.youtube.com/feeds/videos.xml?playlist_id={playlist_id}"
    elif channel_id:
        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    else:
        raise ValueError("youtube playlist/channel source requires playlist_id, channel_id, or url")
    with httpx.Client(follow_redirects=True, timeout=20.0) as client:
        response = client.get(feed_url)
        response.raise_for_status()
    return _rss_links(response.text)


def _query_param(url: str, name: str) -> str:
    match = re.search(rf"[?&]{re.escape(name)}=([^&#]+)", url)
    return match.group(1) if match else ""


def _channel_id(url: str) -> str:
    match = re.search(r"youtube\.com/channel/([^/?#]+)", url)
    return match.group(1) if match else ""


def _kind_for_path(path: Path):
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "paper"
    if suffix in {".md", ".txt", ".html", ".htm"}:
        return "note"
    if suffix in {".py", ".ipynb", ".js", ".ts", ".go", ".rs"}:
        return "code"
    if re.search(r"readme", path.name, re.I):
        return "note"
    return None
