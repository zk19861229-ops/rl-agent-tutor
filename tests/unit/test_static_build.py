from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD_STATIC = ROOT / "scripts" / "build_static.py"
spec = importlib.util.spec_from_file_location("build_static", BUILD_STATIC)
build_static = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(build_static)


def test_static_html_is_generated_from_web_sources():
    assert build_static.STATIC_HTML.read_text(encoding="utf-8") == build_static.render_static_html()
