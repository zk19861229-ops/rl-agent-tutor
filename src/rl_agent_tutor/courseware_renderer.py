"""Courseware rendering facade."""
from __future__ import annotations

from .courseware_schema import Courseware, render_courseware_markdown


def render_markdown(courseware: Courseware) -> str:
    return render_courseware_markdown(courseware)
