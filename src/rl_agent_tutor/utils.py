"""Small shared utilities. Keep this module dependency-free."""
from __future__ import annotations
import re

_SLUG_DEFAULT = re.compile(r"[^a-zA-Z0-9._-]+")
_SLUG_NO_DOT = re.compile(r"[^a-zA-Z0-9_-]+")


def slugify(s: str, n: int = 60, *, allow_dot: bool = False, lower: bool = False) -> str:
    """Slugify a string for safe filename use.

    allow_dot=True keeps `.` (used for filenames where the dot may already
    be embedded in a meaningful identifier, e.g. arxiv ids).
    """
    pat = _SLUG_DEFAULT if allow_dot else _SLUG_NO_DOT
    out = pat.sub("_", s).strip("_")
    if lower:
        out = out.lower()
    return out[:n]
