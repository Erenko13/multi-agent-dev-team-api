from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ProjectStatus(str, Enum):
    queued = "queued"
    running = "running"
    awaiting_approval = "awaiting_approval"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


# --- Requests ---


class CreateProjectRequest(BaseModel):
    requirements: str = Field(..., min_length=1, description="What to build")
    use_sandbox: bool = Field(
        True, description="Run shell commands in Docker sandbox"
    )


class ApprovalRequest(BaseModel):
    approved: bool
    feedback: str = Field(
        "", description="Feedback for revision (used when rejecting)"
    )


# --- Responses ---


class PendingApproval(BaseModel):
    type: str  # "architecture_review" or "final_review"
    data: dict[str, Any]


class ProjectSummary(BaseModel):
    project_id: str
    status: ProjectStatus
    created_at: datetime
    current_agent: str | None = None
    requirements: str


class ProjectDetail(ProjectSummary):
    project_url: str = ""
    events_url: str = ""
    workspace_path: str = ""
    user_stories: list[str] = []
    task_plan: list[dict[str, Any]] = []
    architecture_doc: str = ""
    folder_structure: list[str] = []
    tech_stack: dict[str, str] = {}
    generated_files: list[dict[str, Any]] = []
    review_comments: list[dict[str, Any]] = []
    test_results: list[dict[str, Any]] = []
    tests_passing: bool = False
    review_iteration: int = 0
    error: str | None = None
    pending_approval: PendingApproval | None = None


class ApprovalResponse(BaseModel):
    project_id: str
    approved: bool
    resumed: bool


class ProjectEvent(BaseModel):
    event_type: str
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    agent: str | None = None
    data: dict[str, Any] = {}
