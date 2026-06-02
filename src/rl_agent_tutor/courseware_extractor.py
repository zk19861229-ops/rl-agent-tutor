"""Courseware source extraction and media discovery."""
from __future__ import annotations

import re
from pathlib import Path

from .config import workspace_path
from .courseware_schema import ContentBlock
from .models import LearningNode, Resource
from .store import load_resources
from .utils import slugify


MAX_PER_RESOURCE = 4000
MAX_PAPER_PAGES = 6
MAX_TOTAL_CTX = 28000


def build_materials_block(node: LearningNode) -> tuple[str, list[Resource]]:
    resources = load_resources(node_id=node.id)
    used: list[Resource] = []
    parts: list[str] = []
    total = 0
    for resource in resources:
        excerpt = extract_text(resource)
        if not excerpt:
            continue
        excerpt = excerpt.strip()[:MAX_PER_RESOURCE]
        if total + len(excerpt) > MAX_TOTAL_CTX and parts:
            break
        ident = resource.title[:60] if resource.title else (resource.url or resource.local_path or "")[:60]
        parts.append(f"### {resource.kind}: {ident}\n{excerpt}\n")
        used.append(resource)
        total += len(excerpt)
    if not parts:
        return "(no usable source material — fetch resources first or sources had no content)", []
    return "\n\n".join(parts), used


def extract_text(resource: Resource) -> str | None:
    if is_failed(resource) or not resource.local_path:
        return None
    path = Path(resource.local_path)
    if not path.exists():
        return None
    if resource.kind == "paper" and path.suffix.lower() == ".pdf":
        return read_pdf_text(path)
    if resource.kind in ("blog", "video", "note"):
        return read_text_file(path)
    if resource.kind == "code":
        return read_repo_readme(path)
    return None


def extract_media_blocks(node: LearningNode, resources: list[Resource]) -> list[ContentBlock]:
    blocks: list[ContentBlock] = []
    for resource in resources:
        if len(blocks) >= 3:
            break
        image_path = extract_first_image(node.id, resource)
        if image_path:
            blocks.append(
                ContentBlock(
                    type="image",
                    title=f"图示: {resource.title[:40]}",
                    content={
                        "local_path": image_path,
                        "alt": resource.title,
                        "caption": f"从 {resource.title} 自动抽取的辅助图示。",
                    },
                )
            )
    return blocks


def extract_first_image(node_id: str, resource: Resource) -> str:
    if not resource.local_path:
        return ""
    path = Path(resource.local_path)
    if not path.exists():
        return ""
    if resource.kind == "paper" and path.suffix.lower() == ".pdf":
        return extract_first_pdf_image(node_id, path)
    if resource.kind in {"blog", "note"}:
        return extract_first_markdown_image(path)
    return ""


def extract_first_pdf_image(node_id: str, path: Path) -> str:
    try:
        import fitz  # pymupdf
    except ImportError:
        return ""
    try:
        media_dir = workspace_path("library", "notes", "courseware", "media")
        media_dir.mkdir(parents=True, exist_ok=True)
        with fitz.open(path) as doc:
            for page_index, page in enumerate(doc[:3]):
                images = page.get_images(full=True)
                if not images:
                    continue
                xref = images[0][0]
                pix = fitz.Pixmap(doc, xref)
                if pix.alpha:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                target = media_dir / f"{node_id}_{slugify(path.stem, n=36, lower=True)}_p{page_index + 1}.png"
                pix.save(target)
                return str(target)
    except Exception:
        return ""
    return ""


def extract_first_markdown_image(path: Path) -> str:
    text = read_text_file(path)
    ref = _first_image_ref(text)
    if not ref:
        return ""
    if ref.startswith(("http://", "https://", "data:")):
        return ref
    candidate = (path.parent / ref).resolve()
    return str(candidate) if candidate.exists() else ref


def _first_image_ref(text: str) -> str:
    patterns = [
        r"!\[[^\]]*\]\(([^)]+)\)",
        r"<figure[\s\S]{0,1200}?<img[^>]+(?:src|data-src|data-original)=[\"']([^\"']+)[\"']",
        r"<img[^>]+(?:src|data-src|data-original)=[\"']([^\"']+)[\"']",
        r"<img[^>]+srcset=[\"']([^\"']+)[\"']",
        r"<meta[^>]+(?:property|name)=[\"'](?:og:image|twitter:image)[\"'][^>]+content=[\"']([^\"']+)[\"']",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        ref = match.group(1).strip()
        if "," in ref and " " in ref:
            ref = ref.split(",", 1)[0].strip().split(" ", 1)[0]
        return ref
    return ""


def is_failed(resource: Resource) -> bool:
    title = (resource.title or "").lower()
    summary = (resource.summary or "").lower()
    return title.startswith("[search failed") or any(
        word in summary
        for word in (
            "download failed",
            "clone failed",
            "fetch failed",
            "transcript unavailable",
            "empty content extracted",
        )
    )


def read_pdf_text(path: Path, max_pages: int = MAX_PAPER_PAGES) -> str:
    try:
        import fitz  # pymupdf
    except ImportError:
        return ""
    try:
        with fitz.open(path) as doc:
            pages = []
            for index, page in enumerate(doc):
                if index >= max_pages:
                    break
                pages.append(page.get_text("text"))
        return "\n".join(pages).strip()
    except Exception:
        return ""


def read_repo_readme(path: Path) -> str:
    if not path.exists() or not path.is_dir():
        return ""
    for name in ("README.md", "README.MD", "README.rst", "README.txt", "README"):
        file = path / name
        if file.exists() and file.is_file():
            return read_text_file(file)
    return ""


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
