from __future__ import annotations

import operator
from typing import Annotated, Literal

from langchain_core.messages import BaseMessage
from typing_extensions import TypedDict


class TaskItem(TypedDict):
    id: str
    title: str
    description: str
    status: Literal["pending", "in_progress", "done"]
    assigned_to: Literal["developer", "tester"]


class FileOutput(TypedDict):
    path: str
    content: str
    language: str


class ReviewComment(TypedDict):
    file_path: str
    line_range: str
    severity: Literal["critical", "major", "minor", "suggestion"]
    comment: str


class TestResult(TypedDict):
    test_file: str
    passed: bool
    output: str


class AgentState(TypedDict):
    # Conversation history (append-only)
    messages: Annotated[list[BaseMessage], operator.add]

    # User input
    user_requirements: str

    # PM outputs
    user_stories: list[str]
    task_plan: list[TaskItem]

    # Architect outputs
    architecture_doc: str
    folder_structure: list[str]
    tech_stack: dict[str, str]

    # Human checkpoint flags
    architecture_approved: bool
    final_approved: bool

    # Developer outputs
    generated_files: list[FileOutput]

    # Reviewer outputs
    review_comments: list[ReviewComment]
    review_approved: bool
    review_iteration: int

    # Tester outputs
    test_files: list[FileOutput]
    test_results: list[TestResult]
    tests_passing: bool

    # Metadata
    current_agent: str
    workspace_path: str
    error: str
