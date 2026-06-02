"""Weak-area extraction from self-test feedback."""
from __future__ import annotations

import re

from ..models import ExerciseAttempt


DIMENSION_KEYWORDS = {
    "concept": ("概念", "定义", "理解", "confuse", "missing concept", "误解"),
    "derivation": ("推导", "公式", "梯度", "证明", "derive", "math"),
    "code": ("代码", "实现", "bug", "api", "shape", "tensor", "debug"),
    "experiment": ("实验", "指标", "评估", "ablation", "baseline", "判断"),
    "communication": ("表达", "不清晰", "结构", "遗漏", "unclear", "incomplete"),
}


def extract_weak_areas(attempts: list[ExerciseAttempt]) -> list[dict]:
    areas: dict[str, dict] = {}
    for attempt in attempts:
        if attempt.score >= 0.8:
            continue
        dimension = classify_feedback(attempt.feedback)
        item = areas.setdefault(
            dimension,
            {
                "dimension": dimension,
                "count": 0,
                "avg_score": 0.0,
                "examples": [],
            },
        )
        item["count"] += 1
        item["avg_score"] += attempt.score
        if len(item["examples"]) < 3:
            item["examples"].append(
                {
                    "qid": attempt.qid,
                    "score": attempt.score,
                    "feedback": attempt.feedback[:240],
                }
            )
    out = []
    for item in areas.values():
        item["avg_score"] = item["avg_score"] / item["count"] if item["count"] else 0.0
        out.append(item)
    out.sort(key=lambda x: (-x["count"], x["avg_score"]))
    return out


def classify_feedback(feedback: str) -> str:
    text = re.sub(r"\s+", " ", feedback or "").lower()
    for dimension, keywords in DIMENSION_KEYWORDS.items():
        if any(keyword.lower() in text for keyword in keywords):
            return dimension
    return "concept"
