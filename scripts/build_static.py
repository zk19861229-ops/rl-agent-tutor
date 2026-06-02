"""Build the single-file static UI from the split web sources.

`src/rl_agent_tutor/web/` is the source of truth. The generated
`src/rl_agent_tutor/static/index.html` exists for compatibility with older
single-file consumers and should not be edited by hand.
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "src" / "rl_agent_tutor" / "web"
STATIC_HTML = ROOT / "src" / "rl_agent_tutor" / "static" / "index.html"

CSS_LINK = '<link rel="stylesheet" href="/static/style.css">'
JS_SCRIPT = '<script src="/static/app.js"></script>'


def render_static_html() -> str:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    css = (WEB_DIR / "style.css").read_text(encoding="utf-8")
    js = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    if CSS_LINK not in html:
        raise RuntimeError(f"missing stylesheet marker: {CSS_LINK}")
    if JS_SCRIPT not in html:
        raise RuntimeError(f"missing script marker: {JS_SCRIPT}")

    html = html.replace(CSS_LINK, f"<style>\n{css}\n</style>")
    html = html.replace(JS_SCRIPT, f"<script>\n{js}\n</script>")
    return html


def main() -> None:
    STATIC_HTML.parent.mkdir(parents=True, exist_ok=True)
    STATIC_HTML.write_text(render_static_html(), encoding="utf-8")


if __name__ == "__main__":
    main()
