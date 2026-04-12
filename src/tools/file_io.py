from __future__ import annotations

import os
from pathlib import Path

from langchain_core.tools import tool

from src.utils.workspace import resolve_workspace_path


def make_file_tools(workspace_path: str):
    """Create file I/O tools scoped to a workspace directory."""

    @tool
    def write_file(path: str, content: str) -> str:
        """Write content to a file at the given path within the workspace. Creates parent directories if needed."""
        full_path = resolve_workspace_path(workspace_path, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(content)
        return f"Written: {path} ({len(content)} chars)"

    @tool
    def read_file(path: str) -> str:
        """Read and return the contents of a file at the given path within the workspace."""
        full_path = resolve_workspace_path(workspace_path, path)
        if not os.path.exists(full_path):
            return f"Error: File not found: {path}"
        with open(full_path) as f:
            return f.read()

    @tool
    def list_directory(path: str = ".") -> str:
        """List all files and directories at the given path within the workspace."""
        full_path = resolve_workspace_path(workspace_path, path)
        if not os.path.isdir(full_path):
            return f"Error: Not a directory: {path}"
        entries = []
        for entry in sorted(Path(full_path).rglob("*")):
            rel = entry.relative_to(full_path)
            prefix = "📁 " if entry.is_dir() else "📄 "
            entries.append(f"{prefix}{rel}")
        return "\n".join(entries) if entries else "(empty directory)"

    return write_file, read_file, list_directory
