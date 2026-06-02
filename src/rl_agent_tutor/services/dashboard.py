"""Mastery-oriented dashboard metrics."""
from __future__ import annotations

from dataclasses import dataclass

from ..models import LearningPlan
from ..store import load_exercises, load_resources
from . import weakness
from . import evidence, workflow


MASTERY_DIMENSIONS = {
    "concept": "概念理解",
    "derivation": "推导能力",
    "code": "代码实现",
    "experiment": "实验判断",
    "communication": "表达清晰度",
}

QUESTION_DIMENSION = {
    "concept": "concept",
    "derivation": "derivation",
    "code-debug": "code",
    "discussion": "communication",
}


@dataclass(frozen=True)
class NodeMastery:
    node_id: str
    name: str
    status: str
    latest_score: float | None
    confidence: str
    evidence_used: int
    evidence_total: int
    estimated_hours: float

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "name": self.name,
            "status": self.status,
            "latest_score": self.latest_score,
            "confidence": self.confidence,
            "evidence_used": self.evidence_used,
            "evidence_total": self.evidence_total,
            "estimated_hours": self.estimated_hours,
        }


def build_mastery_dashboard(plan: LearningPlan) -> dict:
    nodes = plan.all_nodes()
    node_mastery = [_node_mastery(node) for node in nodes]
    weak_nodes = [
        item for item in node_mastery
        if item.confidence in {"weak", "unknown"} and item.status != "completed"
    ][:6]

    total_resources = len(load_resources())
    used_resources = sum(1 for resource in load_resources() if resource.used_by)
    done = sum(1 for node in nodes if node.status == "completed")
    scores = [item.latest_score for item in node_mastery if item.latest_score is not None]
    avg_score = sum(scores) / len(scores) if scores else None
    weak_areas = _aggregate_weak_areas()
    dimension_mastery = _dimension_mastery()

    total_hours = sum(item.estimated_hours for item in node_mastery)
    completed_hours = sum(item.estimated_hours for item in node_mastery if item.status == "completed")

    return {
        "mastery": {
            "avg_score": avg_score,
            "solid_nodes": sum(1 for item in node_mastery if item.confidence == "solid"),
            "developing_nodes": sum(1 for item in node_mastery if item.confidence == "developing"),
            "weak_nodes": sum(1 for item in node_mastery if item.confidence == "weak"),
            "unknown_nodes": sum(1 for item in node_mastery if item.confidence == "unknown"),
        },
        "resource_utilization": {
            "total": total_resources,
            "used": used_resources,
            "rate": used_resources / total_resources if total_resources else 0.0,
        },
        "plan_progress": {
            "done_nodes": done,
            "total_nodes": len(nodes),
            "completion_rate": done / len(nodes) if nodes else 0.0,
            "estimated_hours_total": total_hours,
            "estimated_hours_completed": completed_hours,
        },
        "weak_nodes": [item.to_dict() for item in weak_nodes],
        "weak_areas": weak_areas,
        "dimension_mastery": dimension_mastery,
        "nodes": [item.to_dict() for item in node_mastery],
        "recommended_action": workflow.recommend_next_action(plan).to_dict(),
    }


def _node_mastery(node) -> NodeMastery:
    summary = evidence.summarize_node(node.id)
    latest_score = _latest_score(node.id)
    confidence = _confidence(node.status, latest_score, summary.used, summary.total)
    return NodeMastery(
        node_id=node.id,
        name=node.name,
        status=node.status,
        latest_score=latest_score,
        confidence=confidence,
        evidence_used=summary.used,
        evidence_total=summary.total,
        estimated_hours=sum(node.estimated_hours) / 2,
    )


def _latest_score(node_id: str) -> float | None:
    sessions = [
        session
        for session in load_exercises(node_id=node_id)
        if session.overall_score is not None
    ]
    if not sessions:
        return None
    sessions.sort(key=lambda session: session.finished_at or session.started_at)
    return sessions[-1].overall_score


def _confidence(status: str, latest_score: float | None, evidence_used: int, evidence_total: int) -> str:
    if latest_score is not None:
        if latest_score >= 0.8:
            return "solid"
        if latest_score >= 0.6:
            return "developing"
        return "weak"
    if status == "completed":
        return "solid"
    if evidence_used > 0:
        return "developing"
    return "unknown"


def _aggregate_weak_areas() -> list[dict]:
    totals: dict[str, dict] = {}
    for session in load_exercises():
        for area in weakness.extract_weak_areas(session.attempts):
            item = totals.setdefault(
                area["dimension"],
                {"dimension": area["dimension"], "count": 0, "avg_score": 0.0, "examples": []},
            )
            item["count"] += area["count"]
            item["avg_score"] += area["avg_score"] * area["count"]
            item["examples"].extend(area["examples"][:2])
            item["examples"] = item["examples"][:3]
    out = []
    for item in totals.values():
        item["avg_score"] = item["avg_score"] / item["count"] if item["count"] else 0.0
        out.append(item)
    out.sort(key=lambda area: (-area["count"], area["avg_score"]))
    return out[:5]


def _dimension_mastery() -> dict:
    stats = {
        key: {
            "id": key,
            "label": label,
            "attempts": 0,
            "avg_score": None,
            "confidence": "unknown",
            "weak_count": 0,
        }
        for key, label in MASTERY_DIMENSIONS.items()
    }
    score_sums = {key: 0.0 for key in stats}
    for session in load_exercises():
        question_types = {question.qid: question.type for question in session.questions}
        weak_by_feedback = {
            example["qid"]: area["dimension"]
            for area in weakness.extract_weak_areas(session.attempts)
            for example in area["examples"]
        }
        for attempt in session.attempts:
            dimension = weak_by_feedback.get(attempt.qid) or QUESTION_DIMENSION.get(
                question_types.get(attempt.qid, "concept"),
                "concept",
            )
            if dimension not in stats:
                dimension = "concept"
            stats[dimension]["attempts"] += 1
            score_sums[dimension] += attempt.score
            if attempt.score < 0.8:
                stats[dimension]["weak_count"] += 1
    for dimension, item in stats.items():
        if item["attempts"]:
            avg = score_sums[dimension] / item["attempts"]
            item["avg_score"] = avg
            item["confidence"] = _dimension_confidence(avg, item["weak_count"])
    return stats


def _dimension_confidence(avg_score: float, weak_count: int) -> str:
    if avg_score >= 0.85 and weak_count == 0:
        return "solid"
    if avg_score >= 0.7:
        return "developing"
    return "weak"
