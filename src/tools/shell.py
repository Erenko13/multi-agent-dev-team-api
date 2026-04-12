from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from langchain_core.tools import tool

if TYPE_CHECKING:
    from src.utils.container import DockerSandbox

ALLOWED_PREFIXES = [
    "pip install",
    "pip freeze",
    "npm install",
    "npm init",
    "npm run",
    "npm test",
    "npx",
    "node ",
    "python ",
    "python3 ",
    "pytest",
    "ls",
    "cat ",
    "mkdir ",
    "touch ",
    "echo ",
    "cd ",
    "pwd",
    "which ",
    "env ",
]

BLOCKED_PATTERNS = [
    "rm -rf /",
    "sudo",
    "chmod",
    "chown",
    "curl ",
    "wget ",
    "ssh ",
    "scp ",
    "> /dev/",
    "| sh",
    "| bash",
    "eval ",
    "exec ",
]


def _validate_command(command: str) -> str | None:
    """Validate a command against allowlist/blocklist. Returns error string or None if ok."""
    cmd_lower = command.lower().strip()

    for blocked in BLOCKED_PATTERNS:
        if blocked in cmd_lower:
            return f"Error: Blocked command pattern: {blocked}"

    if not any(cmd_lower.startswith(prefix) for prefix in ALLOWED_PREFIXES):
        return f"Error: Command not in allowlist. Allowed prefixes: {', '.join(ALLOWED_PREFIXES)}"

    return None


def make_shell_tool(workspace_path: str, sandbox: DockerSandbox | None = None, container_workdir: str | None = None):
    """Create a shell command tool. If sandbox is provided, commands run inside the Docker container
    at container_workdir (defaults to /workspace if not specified)."""

    @tool
    def run_shell_command(command: str) -> str:
        """Run a shell command in the workspace directory. Returns stdout and stderr. Use for installing dependencies, running tests, etc."""
        error = _validate_command(command)
        if error:
            return error

        if sandbox is not None and sandbox.is_running():
            # Execute inside Docker container at the session's project slot directory
            workdir = container_workdir or "/workspace"
            output, exit_code = sandbox.exec(command, workdir=workdir)
            if exit_code != 0:
                output += f"\n[exit code: {exit_code}]"
            return output

        # Fallback: direct execution on host
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=workspace_path,
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"
            if result.returncode != 0:
                output += f"\n[exit code: {result.returncode}]"
            return output.strip() or "(no output)"
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 120 seconds"
        except Exception as e:
            return f"Error: {e}"

    return run_shell_command
