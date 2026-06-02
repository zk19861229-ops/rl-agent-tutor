"""Data models for plans, nodes, trajectory, exercises."""
from __future__ import annotations
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


NodeStatus = Literal["pending", "in_progress", "self_testing", "completed"]
PlanState = Literal["planning", "studying", "self_testing", "reviewing", "advancing", "done"]


class LearningNode(BaseModel):
    id: str  # e.g. "0.1"
    name: str
    description: str
    objectives: list[str] = Field(default_factory=list)
    estimated_hours: tuple[float, float] = (1.0, 3.0)
    status: NodeStatus = "pending"
    notes: str = ""
    completed_at: Optional[str] = None


class Stage(BaseModel):
    id: int
    name: str
    description: str = ""
    nodes: list[LearningNode] = Field(default_factory=list)


class LearningPlan(BaseModel):
    goal: str
    starting_level: str = ""
    stages: list[Stage] = Field(default_factory=list)
    state: PlanState = "planning"
    current_node_id: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    def all_nodes(self) -> list[LearningNode]:
        return [n for s in self.stages for n in s.nodes]

    def find_node(self, node_id: str) -> Optional[LearningNode]:
        for n in self.all_nodes():
            if n.id == node_id:
                return n
        return None

    def stage_of(self, node_id: str) -> Optional[Stage]:
        for s in self.stages:
            if any(n.id == node_id for n in s.nodes):
                return s
        return None

    def next_pending_node(self) -> Optional[LearningNode]:
        for n in self.all_nodes():
            if n.status in ("pending", "in_progress", "self_testing"):
                return n
        return None


class Resource(BaseModel):
    node_id: str
    kind: Literal["paper", "code", "video", "blog", "note"]
    title: str
    url: Optional[str] = None
    local_path: Optional[str] = None
    fetched_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    summary: str = ""
    source_id: str = ""
    priority: Literal["core", "normal", "supplemental"] = "normal"
    status: Literal[
        "recommended",
        "fetched",
        "read",
        "cited",
        "tested",
        "archived",
        "rejected",
    ] = "fetched"
    used_by: list[str] = Field(default_factory=list)


class TrajectoryEntry(BaseModel):
    ts: str = Field(default_factory=lambda: datetime.now().isoformat())
    node_id: Optional[str] = None
    kind: Literal["plan", "study", "ask", "answer", "fetch", "test", "advance", "review"]
    content: str
    meta: dict = Field(default_factory=dict)


class ExerciseQuestion(BaseModel):
    qid: str
    type: Literal["concept", "derivation", "code-debug", "discussion"]
    question: str
    expected_points: list[str] = Field(default_factory=list)


class ExerciseAttempt(BaseModel):
    qid: str
    answer: str
    score: float  # 0..1
    feedback: str
    attempted_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class ExerciseSession(BaseModel):
    node_id: str
    questions: list[ExerciseQuestion]
    attempts: list[ExerciseAttempt] = Field(default_factory=list)
    started_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    finished_at: Optional[str] = None
    overall_score: Optional[float] = None
