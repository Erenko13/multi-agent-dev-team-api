"""Tests for the state schema."""
from src.state import AgentState, FileOutput, ReviewComment, TaskItem, TestResult


def test_task_item_structure():
    task = TaskItem(
        id="T1",
        title="Setup project",
        description="Initialize the project structure",
        status="pending",
        assigned_to="developer",
    )
    assert task["id"] == "T1"
    assert task["status"] == "pending"
    assert task["assigned_to"] == "developer"


def test_file_output_structure():
    f = FileOutput(path="app.py", content="print('hello')", language="python")
    assert f["path"] == "app.py"
    assert f["language"] == "python"


def test_review_comment_structure():
    c = ReviewComment(
        file_path="app.py",
        line_range="1-5",
        severity="major",
        comment="Missing error handling",
    )
    assert c["severity"] == "major"


def test_test_result_structure():
    r = TestResult(test_file="test_app.py", passed=True, output="1 passed")
    assert r["passed"] is True
