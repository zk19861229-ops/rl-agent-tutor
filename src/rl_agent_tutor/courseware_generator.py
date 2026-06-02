"""Courseware assembly helpers."""
from __future__ import annotations

from .courseware_schema import ContentBlock, Courseware, CoursewareSection


def attach_media_blocks(courseware: Courseware, blocks: list[ContentBlock]) -> Courseware:
    if not blocks:
        return courseware
    if not courseware.sections:
        courseware.sections.append(
            CoursewareSection(id="media", title="图文资料", type="case_study", blocks=[])
        )
    target = courseware.sections[0]
    existing = {
        str(block.content.get("local_path") or block.content.get("url") or "")
        for section in courseware.sections
        for block in section.blocks
        if block.type == "image"
    }
    for block in blocks:
        key = str(block.content.get("local_path") or block.content.get("url") or "")
        if key and key not in existing:
            target.blocks.append(block)
            existing.add(key)
    return courseware
