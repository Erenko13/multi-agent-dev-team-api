from __future__ import annotations

import subprocess
import uuid


SANDBOX_IMAGE = "devteam-sandbox"
CONTAINER_PREFIX = "devteam-"
WORKSPACE_CONTAINER_PATH = "/workspace"


class DockerSandbox:
    """Manages a Docker container that acts as an isolated dev environment.

    Architecture:
    - Host ./output/ is bind-mounted to /workspace inside the container
    - The 5 project slots live at /workspace/project_1 … /workspace/project_5
    - File tools write to ./output/project_X/ on the host (visible in the container
      at /workspace/project_X/ via the bind mount)
    - Shell commands execute inside the container via `docker exec -w <slot_dir>`
    - One container is shared across all sessions for the server lifetime
    """

    def __init__(self, host_output_dir: str):
        self.host_output_dir = host_output_dir
        self.container_name = f"{CONTAINER_PREFIX}{uuid.uuid4().hex[:8]}"
        self.container_id: str | None = None

    def build_image(self) -> None:
        """Build the sandbox Docker image if it doesn't exist."""
        result = subprocess.run(
            ["docker", "images", "-q", SANDBOX_IMAGE],
            capture_output=True, text=True,
        )
        if result.stdout.strip():
            return  # Image already exists

        # Find the Dockerfile relative to this file
        import os
        dockerfile_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "sandbox"
        )
        dockerfile_dir = os.path.abspath(dockerfile_dir)

        subprocess.run(
            ["docker", "build", "-t", SANDBOX_IMAGE, dockerfile_dir],
            check=True,
        )

    def start(self) -> None:
        """Build image and start the sandbox container."""
        self.build_image()

        result = subprocess.run(
            [
                "docker", "run", "-d",
                "--name", self.container_name,
                "-v", f"{self.host_output_dir}:{WORKSPACE_CONTAINER_PATH}",
                "-w", WORKSPACE_CONTAINER_PATH,
                "--memory", "2g",
                "--cpus", "2",
                "--network", "bridge",
                SANDBOX_IMAGE,
            ],
            capture_output=True, text=True, check=True,
        )
        self.container_id = result.stdout.strip()

    def exec(self, command: str, workdir: str = WORKSPACE_CONTAINER_PATH, timeout: int = 120) -> tuple[str, int]:
        """Execute a command inside the container at the given workdir. Returns (output, exit_code)."""
        if not self.container_id:
            raise RuntimeError("Container not started")

        try:
            result = subprocess.run(
                ["docker", "exec", "-w", workdir, self.container_name, "sh", "-c", command],
                capture_output=True, text=True, timeout=timeout,
            )
            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"
            return output.strip() or "(no output)", result.returncode
        except subprocess.TimeoutExpired:
            return f"Error: Command timed out after {timeout} seconds", 1

    def stop(self) -> None:
        """Stop and remove the container."""
        if not self.container_id:
            return
        subprocess.run(
            ["docker", "rm", "-f", self.container_name],
            capture_output=True, text=True,
        )
        self.container_id = None

    def is_running(self) -> bool:
        """Check if the container is still running."""
        if not self.container_id:
            return False
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", self.container_name],
            capture_output=True, text=True,
        )
        return result.stdout.strip() == "true"

    @staticmethod
    def is_docker_available() -> bool:
        """Check if Docker is available on the host."""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
