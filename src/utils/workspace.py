from __future__ import annotations

import os
from pathlib import Path


def prepare_workspace(output_dir: str) -> str:
    """Create and return the absolute path to the workspace directory."""
    workspace = Path(output_dir).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    return str(workspace)


def resolve_workspace_path(workspace_path: str, relative_path: str) -> str:
    """Resolve a relative path within the workspace, preventing path traversal."""
    workspace = Path(workspace_path).resolve()
    full_path = (workspace / relative_path).resolve()
    if not str(full_path).startswith(str(workspace)):
        raise ValueError(f"Path traversal detected: {relative_path}")
    return str(full_path)
