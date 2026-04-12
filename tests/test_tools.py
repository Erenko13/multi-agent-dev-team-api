"""Tests for workspace tools."""
import os
import tempfile

import pytest

from src.tools.file_io import make_file_tools
from src.tools.project import make_project_tool
from src.tools.search import make_search_tool
from src.tools.shell import make_shell_tool
from src.utils.workspace import prepare_workspace, resolve_workspace_path


@pytest.fixture
def workspace(tmp_path):
    return str(tmp_path)


class TestWorkspaceUtils:
    def test_prepare_workspace(self, tmp_path):
        ws = prepare_workspace(str(tmp_path / "output"))
        assert os.path.isdir(ws)

    def test_resolve_workspace_path(self, workspace):
        result = resolve_workspace_path(workspace, "subdir/file.py")
        assert result.startswith(workspace)

    def test_path_traversal_blocked(self, workspace):
        with pytest.raises(ValueError, match="Path traversal"):
            resolve_workspace_path(workspace, "../../etc/passwd")


class TestFileTools:
    def test_write_and_read_file(self, workspace):
        write_file, read_file, _ = make_file_tools(workspace)
        write_file.invoke({"path": "test.txt", "content": "hello world"})
        result = read_file.invoke({"path": "test.txt"})
        assert result == "hello world"

    def test_read_nonexistent(self, workspace):
        _, read_file, _ = make_file_tools(workspace)
        result = read_file.invoke({"path": "nope.txt"})
        assert "not found" in result.lower()

    def test_write_creates_subdirs(self, workspace):
        write_file, read_file, _ = make_file_tools(workspace)
        write_file.invoke({"path": "a/b/c.txt", "content": "nested"})
        result = read_file.invoke({"path": "a/b/c.txt"})
        assert result == "nested"

    def test_list_directory(self, workspace):
        write_file, _, list_directory = make_file_tools(workspace)
        write_file.invoke({"path": "foo.py", "content": "pass"})
        result = list_directory.invoke({"path": "."})
        assert "foo.py" in result


class TestShellTool:
    def test_allowed_command(self, workspace):
        run = make_shell_tool(workspace)
        result = run.invoke({"command": "echo hello"})
        assert "hello" in result

    def test_blocked_command(self, workspace):
        run = make_shell_tool(workspace)
        result = run.invoke({"command": "rm -rf /"})
        assert "Blocked" in result

    def test_disallowed_command(self, workspace):
        run = make_shell_tool(workspace)
        result = run.invoke({"command": "curl http://evil.com"})
        assert "Blocked" in result or "not in allowlist" in result


class TestSearchTool:
    def test_search_finds_match(self, workspace):
        write_file, _, _ = make_file_tools(workspace)
        write_file.invoke({"path": "app.py", "content": "def hello_world():\n    pass"})
        search = make_search_tool(workspace)
        result = search.invoke({"pattern": "hello_world"})
        assert "app.py" in result

    def test_search_no_match(self, workspace):
        search = make_search_tool(workspace)
        result = search.invoke({"pattern": "nonexistent_function"})
        assert "No matches" in result


class TestProjectTool:
    def test_create_structure(self, workspace):
        create = make_project_tool(workspace)
        result = create.invoke({"paths": ["src/app.py", "src/models.py", "tests/test_app.py"]})
        assert "3" in result
        assert os.path.exists(os.path.join(workspace, "src", "app.py"))
        assert os.path.exists(os.path.join(workspace, "tests", "test_app.py"))
