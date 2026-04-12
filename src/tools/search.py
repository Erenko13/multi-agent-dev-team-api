from __future__ import annotations

import os
import re
from pathlib import Path

from langchain_core.tools import tool

from src.utils.workspace import resolve_workspace_path

BINARY_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".pyc", ".pyo"}


def make_search_tool(workspace_path: str):
    """Create a codebase search tool scoped to a workspace directory."""

    @tool
    def search_codebase(pattern: str, path: str = ".") -> str:
        """Search for a regex pattern across all files in the workspace. Returns matching lines with file paths and line numbers."""
        search_root = resolve_workspace_path(workspace_path, path)

        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return f"Error: Invalid regex: {e}"

        matches = []
        for filepath in Path(search_root).rglob("*"):
            if not filepath.is_file():
                continue
            if filepath.suffix in BINARY_EXTENSIONS:
                continue
            try:
                with open(filepath) as f:
                    for i, line in enumerate(f, 1):
                        if regex.search(line):
                            rel = filepath.relative_to(workspace_path)
                            matches.append(f"{rel}:{i}: {line.rstrip()}")
                            if len(matches) >= 100:
                                matches.append("... (truncated at 100 matches)")
                                return "\n".join(matches)
            except (UnicodeDecodeError, PermissionError):
                continue

        return "\n".join(matches) if matches else f"No matches for: {pattern}"

    return search_codebase
