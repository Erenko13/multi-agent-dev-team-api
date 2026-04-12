from __future__ import annotations

import os

from langchain_core.tools import tool

from src.utils.workspace import resolve_workspace_path


def make_project_tool(workspace_path: str):
    """Create a project structure tool scoped to a workspace directory."""

    @tool
    def create_project_structure(paths: list[str]) -> str:
        """Create the full project directory structure. Takes a list of file paths and creates all necessary directories and empty files."""
        created = []
        for path in paths:
            full_path = resolve_workspace_path(workspace_path, path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            if not os.path.exists(full_path):
                with open(full_path, "w") as f:
                    f.write("")
                created.append(path)
        return f"Created {len(created)} files/directories: {', '.join(created[:20])}"

    return create_project_structure
