"""Tests for graph routing logic."""
from src.graph import (
    route_after_architecture_approval,
    route_after_final_approval,
    route_after_review,
)


def _make_state(**overrides) -> dict:
    base = {
        "messages": [],
        "user_requirements": "",
        "user_stories": [],
        "task_plan": [],
        "architecture_doc": "",
        "folder_structure": [],
        "tech_stack": {},
        "architecture_approved": False,
        "final_approved": False,
        "generated_files": [],
        "review_comments": [],
        "review_approved": False,
        "review_iteration": 0,
        "test_files": [],
        "test_results": [],
        "tests_passing": False,
        "current_agent": "",
        "workspace_path": "/tmp",
        "error": "",
        "_max_review_iterations": 3,
    }
    base.update(overrides)
    return base


class TestRouteAfterArchitectureApproval:
    def test_approved(self):
        state = _make_state(architecture_approved=True)
        assert route_after_architecture_approval(state) == "developer_agent"

    def test_rejected(self):
        state = _make_state(architecture_approved=False)
        assert route_after_architecture_approval(state) == "architect_agent"


class TestRouteAfterReview:
    def test_approved(self):
        state = _make_state(review_approved=True)
        assert route_after_review(state) == "tester_agent"

    def test_rejected_under_limit(self):
        state = _make_state(review_approved=False, review_iteration=1)
        assert route_after_review(state) == "developer_agent"

    def test_rejected_at_limit(self):
        state = _make_state(review_approved=False, review_iteration=3)
        assert route_after_review(state) == "tester_agent"

    def test_rejected_over_limit(self):
        state = _make_state(review_approved=False, review_iteration=5)
        assert route_after_review(state) == "tester_agent"


class TestRouteAfterFinalApproval:
    def test_approved(self):
        state = _make_state(final_approved=True)
        result = route_after_final_approval(state)
        assert result == "__end__"

    def test_rejected(self):
        state = _make_state(final_approved=False)
        assert route_after_final_approval(state) == "developer_agent"
