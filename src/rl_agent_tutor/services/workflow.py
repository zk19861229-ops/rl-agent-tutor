"""Coach-style workflow recommendations for the current learning node."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..config import workspace_path
from ..models import LearningNode, LearningPlan, TrajectoryEntry
from ..store import append_trajectory

from ..store import load_exercises, load_resources, load_trajectory
from . import evidence


@dataclass(frozen=True)
class RecommendedAction:
    id: str
    label: str
    reason: str
    primary_endpoint: str = ""
    method: str = "POST"
    view: str = "study"
    blocking_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "reason": self.reason,
            "primary_endpoint": self.primary_endpoint,
            "method": self.method,
            "view": self.view,
            "blocking_reason": self.blocking_reason,
        }


def recommend_next_action(plan: LearningPlan) -> RecommendedAction:
    if plan.state == "done":
        return RecommendedAction(
            id="review",
            label="生成阶段复盘",
            reason="学习计划已经完成，下一步应沉淀阶段总结和知识地图。",
            primary_endpoint="/api/review/weekly",
            view="review",
        )

    node = plan.find_node(plan.current_node_id) if plan.current_node_id else None
    if not node:
        return RecommendedAction(
            id="create_plan",
            label="生成学习计划",
            reason="当前还没有可推进的学习节点。",
            primary_endpoint="/api/plan",
            blocking_reason="no_current_node",
        )

    if node.status == "completed":
        return RecommendedAction(
            id="advance",
            label="进入下一节点",
            reason="当前节点已完成，需要切换到下一个待学习节点。",
            primary_endpoint="/api/advance",
        )

    if plan.state == "advancing":
        return RecommendedAction(
            id="advance",
            label="完成并推进",
            reason="最近一次自测已达标，可以确认完成当前节点。",
            primary_endpoint="/api/advance",
        )

    if plan.state == "self_testing":
        return RecommendedAction(
            id="continue_test",
            label="继续自测",
            reason="当前计划处于自测状态，先完成测验再决定是否推进。",
            primary_endpoint="/api/test/start",
            view="test",
        )

    latest_score = _latest_score(node.id)
    if latest_score is not None and latest_score < 0.8:
        return RecommendedAction(
            id="remediate",
            label="补弱复习",
            reason=f"最近一次自测分数为 {latest_score:.2f}，低于推进阈值 0.80。",
            primary_endpoint="/api/remediation",
        )

    resources = load_resources(node_id=node.id)
    if not resources:
        return RecommendedAction(
            id="fetch_resources",
            label="获取核心材料",
            reason="当前节点还没有资源，先抓取论文、代码、文章或视频作为学习依据。",
            primary_endpoint="/api/fetch",
        )

    summary = evidence.summarize_node(node.id)
    if summary.used == 0 or not _has_studied_resource(summary.by_status):
        return RecommendedAction(
            id="generate_courseware",
            label="生成结构化课件",
            reason="已有资源但还没有进入学习证据链，先把核心材料转成可学习课件。",
            primary_endpoint="/api/courseware",
        )

    if latest_score is None:
        return RecommendedAction(
            id="start_test",
            label="开始自测",
            reason="已有学习材料和使用记录，下一步需要用自测验证是否真的掌握。",
            primary_endpoint="/api/test/start",
            view="test",
        )

    if latest_score >= 0.8:
        return RecommendedAction(
            id="advance",
            label="完成并推进",
            reason=f"最近一次自测分数为 {latest_score:.2f}，达到推进阈值。",
            primary_endpoint="/api/advance",
        )

    return RecommendedAction(
        id="ask_tutor",
        label="问 Tutor",
        reason="继续围绕当前节点澄清问题，积累足够理解后再自测。",
        primary_endpoint="/api/ask",
    )


def suggest_next_action_text(plan: LearningPlan) -> str:
    """Human-readable workflow hint.

    `orchestrator` owns state transitions; this service owns learner-facing
    recommendations and action copy.
    """
    cur = plan.find_node(plan.current_node_id) if plan.current_node_id else None
    if plan.state == "done":
        return "Plan complete. Generate a weekly/stage review or start a new goal."
    if not cur:
        return 'Run `rl-agent plan "<your goal>"` to start.'
    action = recommend_next_action(plan)
    return f"{action.label}: {action.reason}"


def _latest_score(node_id: str) -> float | None:
    sessions = [
        session
        for session in load_exercises(node_id=node_id)
        if session.overall_score is not None
    ]
    if not sessions:
        return None
    sessions.sort(key=lambda s: s.finished_at or s.started_at)
    return sessions[-1].overall_score


def _has_studied_resource(by_status: dict[str, int]) -> bool:
    return any(by_status.get(status, 0) > 0 for status in ("read", "cited", "tested", "archived"))


def workflow_summary(plan: LearningPlan) -> dict:
    node = plan.find_node(plan.current_node_id) if plan.current_node_id else None
    action = recommend_next_action(plan)
    if not node:
        return {"recommended_action": action.to_dict(), "evidence": None, "latest_score": None}
    return {
        "recommended_action": action.to_dict(),
        "evidence": evidence.summarize_node(node.id).to_dict(),
        "latest_score": _latest_score(node.id),
        "activity_count": len(load_trajectory(node_id=node.id, limit=200)),
    }


def generate_remediation_package(node: LearningNode) -> dict:
    sessions = [
        session
        for session in load_exercises(node_id=node.id)
        if session.overall_score is not None
    ]
    sessions.sort(key=lambda session: session.finished_at or session.started_at)
    latest = sessions[-1] if sessions else None

    weak_attempts = []
    if latest:
        weak_attempts = [attempt for attempt in latest.attempts if attempt.score < 0.8]

    tasks = []
    if not latest:
        tasks.append("完成一组自测，先建立当前掌握度基线。")
    elif not weak_attempts:
        tasks.append("复盘本次低分的整体原因，并重新生成一组自测确认掌握度。")
    else:
        for index, attempt in enumerate(weak_attempts[:5], start=1):
            tasks.append(
                f"补弱 {index}: 重新回答 `{attempt.qid}`，先写出关键概念，再对照反馈修正。"
            )

    resources = load_resources(node_id=node.id)
    used_resources = [resource for resource in resources if resource.used_by]
    if used_resources:
        tasks.append(f"回看核心资源 `{used_resources[0].title}`，摘录 3 条能解释错题的证据。")
    else:
        tasks.append("先生成结构化课件，让资源进入证据链后再补弱。")

    questions = [
        "我错在哪里：概念、公式、代码、实验判断，还是表达不完整？",
        "如果换一个例子，我还能解释同一个机制吗？",
        "推进前我能否不用提示写出最小可运行思路？",
    ]
    score = latest.overall_score if latest else None
    target = workspace_path("library", "notes", "nudges", f"{node.id}_remediation.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    markdown = "\n".join(
        [
            f"# {node.id} {node.name} 补弱任务包",
            "",
            f"- 生成时间: {datetime.now().isoformat(timespec='seconds')}",
            f"- 最近自测: {score:.2f}" if score is not None else "- 最近自测: 暂无",
            "",
            "## 补弱任务",
            *[f"{index}. {task}" for index, task in enumerate(tasks, start=1)],
            "",
            "## 重新自检",
            *[f"- {question}" for question in questions],
        ]
    )
    target.write_text(markdown, encoding="utf-8")
    append_trajectory(
        TrajectoryEntry(
            node_id=node.id,
            kind="study",
            content=f"generated remediation package: {target.name}",
            meta={"score": score, "weak_attempts": len(weak_attempts), "file": str(target)},
        )
    )
    return {
        "node_id": node.id,
        "file": str(target),
        "markdown": markdown,
        "tasks": tasks,
        "latest_score": score,
    }
