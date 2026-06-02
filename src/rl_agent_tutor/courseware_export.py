"""Export structured courseware to portable files."""
from __future__ import annotations

import html
import re
from pathlib import Path

from .config import workspace_path
from .courseware_schema import Courseware, render_courseware_markdown
from .utils import slugify


def export_courseware(courseware: Courseware, formats: list[str] | None = None) -> dict:
    formats = formats or ["markdown", "html", "pdf"]
    out_dir = workspace_path("library", "exports")
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{courseware.node_id}_{slugify(courseware.title, n=48, lower=True) or 'courseware'}"
    markdown = render_courseware_markdown(courseware)
    files: dict[str, str] = {}

    if "markdown" in formats or "md" in formats:
        target = out_dir / f"{stem}.md"
        target.write_text(markdown + "\n", encoding="utf-8")
        files["markdown"] = str(target)
    if "html" in formats:
        target = out_dir / f"{stem}.html"
        target.write_text(_markdown_to_html(markdown), encoding="utf-8")
        files["html"] = str(target)
    if "pdf" in formats:
        target = out_dir / f"{stem}.pdf"
        _write_basic_pdf(target, courseware.title, markdown)
        files["pdf"] = str(target)

    return {"node_id": courseware.node_id, "files": files}


def _markdown_to_html(markdown: str) -> str:
    body = html.escape(markdown)
    body = re.sub(r"^# (.+)$", r"<h1>\1</h1>", body, flags=re.M)
    body = re.sub(r"^## (.+)$", r"<h2>\1</h2>", body, flags=re.M)
    body = re.sub(r"^### (.+)$", r"<h3>\1</h3>", body, flags=re.M)
    body = re.sub(r"```(\w*)\n([\s\S]*?)```", r"<pre><code>\2</code></pre>", body)
    body = re.sub(r"^- (.+)$", r"<li>\1</li>", body, flags=re.M)
    body = re.sub(r"(<li>[\s\S]*?</li>\n?)+", lambda m: "<ul>" + m.group(0) + "</ul>", body)
    body = body.replace("\n\n", "</p><p>").replace("\n", "<br>")
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<style>body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:880px;margin:32px auto;line-height:1.6}"
        "pre{background:#f6f8fa;padding:12px;overflow:auto}code{font-family:ui-monospace,monospace}</style>"
        "</head><body><p>" + body + "</p></body></html>"
    )


def _write_basic_pdf(target: Path, title: str, markdown: str) -> None:
    try:
        import fitz  # pymupdf
    except ImportError:
        target.write_bytes(_minimal_pdf_bytes(title, markdown))
        return

    doc = fitz.open()
    page = doc.new_page()
    text = re.sub(r"[#*_`>\[\]()]|\|", "", markdown)
    y = 48
    for line in text.splitlines()[:120]:
        if y > 780:
            page = doc.new_page()
            y = 48
        page.insert_text((48, y), line[:110], fontsize=10)
        y += 14
    doc.save(target)
    doc.close()


def _minimal_pdf_bytes(title: str, markdown: str) -> bytes:
    text = re.sub(r"[^\x20-\x7E\n]", "?", f"{title}\n\n{markdown}")[:3000]
    stream = "BT /F1 10 Tf 50 780 Td " + " T* ".join(
        f"({line[:90].replace('(', '[').replace(')', ']')})"
        for line in text.splitlines()[:80]
    ) + " ET"
    objects = [
        "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
        "2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj",
        "3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj",
        "4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj",
        f"5 0 obj << /Length {len(stream)} >> stream\n{stream}\nendstream endobj",
    ]
    body = "%PDF-1.4\n" + "\n".join(objects) + "\ntrailer << /Root 1 0 R >>\n%%EOF\n"
    return body.encode("latin-1", errors="replace")
