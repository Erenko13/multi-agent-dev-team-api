from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from langgraph.types import Command

from src.api.schemas import PendingApproval, ProjectEvent, ProjectStatus
from src.config import AppConfig
from src.graph import compile_graph
from src.utils.container import DockerSandbox
from src.utils.workspace import prepare_workspace

logger = logging.getLogger(__name__)


@dataclass
class PipelineSession:
    project_id: str
    status: ProjectStatus
    created_at: datetime
    requirements: str
    workspace_path: str
    thread_id: str
    graph: Any  # CompiledStateGraph
    config: AppConfig
    sandbox: DockerSandbox | None = None
    task: asyncio.Task | None = None  # type: ignore[type-arg]
    error: str | None = None

    # Approval bridge
    approval_event: asyncio.Event = field(default_factory=asyncio.Event)
    pending_resume_value: dict | None = None
    pending_interrupt: dict | None = None

    # SSE fan-out: one queue per subscriber
    _event_queues: list[asyncio.Queue] = field(default_factory=list)  # type: ignore[type-arg]

    def publish_event(self, event: ProjectEvent) -> None:
        for q in self._event_queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # drop if subscriber is too slow

    def add_subscriber(self) -> asyncio.Queue:  # type: ignore[type-arg]
        q: asyncio.Queue = asyncio.Queue(maxsize=256)  # type: ignore[type-arg]
        self._event_queues.append(q)
        return q

    def remove_subscriber(self, q: asyncio.Queue) -> None:  # type: ignore[type-arg]
        try:
            self._event_queues.remove(q)
        except ValueError:
            pass


class SessionManager:
    """Manages the lifecycle of pipeline sessions.

    Each session owns its own compiled graph, checkpointer, workspace,
    and optional Docker sandbox. Pipelines run as background asyncio tasks.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._sessions: dict[str, PipelineSession] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_session(
        self, requirements: str, use_sandbox: bool = True
    ) -> PipelineSession:
        project_id = uuid.uuid4().hex[:12]
        thread_id = str(uuid.uuid4())

        # Per-session workspace: output_dir / project_id
        base_output = self._config.output_dir
        session_output = os.path.join(base_output, project_id)
        workspace_path = prepare_workspace(session_output)

        # Optionally start a Docker sandbox
        sandbox: DockerSandbox | None = None
        if use_sandbox and self._config.use_sandbox:
            if DockerSandbox.is_docker_available():
                sandbox = DockerSandbox(workspace_path)
                try:
                    await asyncio.to_thread(sandbox.start)
                    logger.info("Sandbox started: %s", sandbox.container_name)
                except Exception:
                    logger.warning("Failed to start sandbox, falling back to host", exc_info=True)
                    sandbox = None

        graph = compile_graph(self._config, sandbox=sandbox)

        session = PipelineSession(
            project_id=project_id,
            status=ProjectStatus.queued,
            created_at=datetime.now(timezone.utc),
            requirements=requirements,
            workspace_path=workspace_path,
            thread_id=thread_id,
            graph=graph,
            config=self._config,
            sandbox=sandbox,
        )
        self._sessions[project_id] = session
        return session

    def start_pipeline(self, project_id: str) -> None:
        session = self._get_session(project_id)
        session.task = asyncio.create_task(
            self._run_pipeline(session),
            name=f"pipeline-{project_id}",
        )

    async def submit_approval(
        self, project_id: str, approved: bool, feedback: str = ""
    ) -> bool:
        session = self._get_session(project_id)
        if session.status != ProjectStatus.awaiting_approval:
            return False

        session.pending_resume_value = {
            "approved": approved,
            "feedback": feedback,
        }
        session.approval_event.set()
        return True

    def get_state_snapshot(self, project_id: str) -> dict[str, Any]:
        """Return the current graph checkpoint state merged with session metadata."""
        session = self._get_session(project_id)
        run_config = {"configurable": {"thread_id": session.thread_id}}

        state: dict[str, Any] = {}
        try:
            snapshot = session.graph.get_state(run_config)
            state = dict(snapshot.values) if snapshot.values else {}
        except Exception:
            logger.debug("Could not read graph state for %s", project_id, exc_info=True)

        # Build pending approval info
        pending = self._extract_pending_approval(session)

        state.update({
            "project_id": session.project_id,
            "status": session.status,
            "created_at": session.created_at,
            "requirements": session.requirements,
            "workspace_path": session.workspace_path,
            "error": session.error,
            "pending_approval": pending,
        })
        return state

    def subscribe_events(
        self, project_id: str
    ) -> tuple[asyncio.Queue, PipelineSession]:  # type: ignore[type-arg]
        session = self._get_session(project_id)
        q = session.add_subscriber()
        return q, session

    def unsubscribe_events(
        self, project_id: str, q: asyncio.Queue  # type: ignore[type-arg]
    ) -> None:
        session = self._sessions.get(project_id)
        if session:
            session.remove_subscriber(q)

    async def cancel_session(self, project_id: str) -> None:
        session = self._get_session(project_id)
        if session.task and not session.task.done():
            session.task.cancel()
        session.status = ProjectStatus.cancelled
        session.publish_event(
            ProjectEvent(event_type="pipeline_cancelled")
        )
        await self._cleanup_sandbox(session)

    def list_sessions(
        self, status: ProjectStatus | None = None
    ) -> list[PipelineSession]:
        sessions = list(self._sessions.values())
        if status is not None:
            sessions = [s for s in sessions if s.status == status]
        return sessions

    def get_session(self, project_id: str) -> PipelineSession | None:
        return self._sessions.get(project_id)

    async def shutdown(self) -> None:
        """Cancel all running sessions and clean up."""
        for session in self._sessions.values():
            if session.task and not session.task.done():
                session.task.cancel()
            await self._cleanup_sandbox(session)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_session(self, project_id: str) -> PipelineSession:
        session = self._sessions.get(project_id)
        if session is None:
            raise KeyError(f"Session not found: {project_id}")
        return session

    def _extract_pending_approval(
        self, session: PipelineSession
    ) -> PendingApproval | None:
        if session.status != ProjectStatus.awaiting_approval:
            return None
        if session.pending_interrupt is None:
            return None
        return PendingApproval(
            type=session.pending_interrupt.get("type", "unknown"),
            data=session.pending_interrupt,
        )

    async def _cleanup_sandbox(self, session: PipelineSession) -> None:
        if session.sandbox is not None:
            try:
                await asyncio.to_thread(session.sandbox.stop)
                logger.info("Sandbox stopped for %s", session.project_id)
            except Exception:
                logger.warning(
                    "Failed to stop sandbox for %s",
                    session.project_id,
                    exc_info=True,
                )

    async def _run_pipeline(self, session: PipelineSession) -> None:
        """Background task that runs the LangGraph pipeline to completion."""
        session.status = ProjectStatus.running
        session.publish_event(
            ProjectEvent(event_type="pipeline_started", data={"project_id": session.project_id})
        )

        run_config = {"configurable": {"thread_id": session.thread_id}}

        initial_state: dict[str, Any] = {
            "user_requirements": session.requirements,
            "messages": [],
            "workspace_path": session.workspace_path,
            "review_iteration": 0,
            "architecture_approved": False,
            "final_approved": False,
            "review_approved": False,
            "generated_files": [],
            "review_comments": [],
            "test_files": [],
            "test_results": [],
            "tests_passing": False,
            "user_stories": [],
            "task_plan": [],
            "architecture_doc": "",
            "folder_structure": [],
            "tech_stack": {},
            "current_agent": "",
            "error": "",
            "_max_review_iterations": session.config.max_review_iterations,
        }

        try:
            input_val: Any = initial_state
            is_first = True

            while True:
                # Run graph.stream() in a thread to avoid blocking the event loop
                events = await asyncio.to_thread(
                    self._stream_graph, session, input_val, run_config
                )

                # Publish per-node events
                for node_name, node_output in events:
                    session.publish_event(
                        ProjectEvent(
                            event_type="agent_completed",
                            agent=node_name,
                            data={"output_keys": list(node_output.keys())},
                        )
                    )

                # Check if graph is done or paused at an interrupt
                snapshot = await asyncio.to_thread(
                    session.graph.get_state, run_config
                )

                if not snapshot.next:
                    # Graph completed
                    break

                # Check for pending interrupts
                interrupt_value = self._find_interrupt(snapshot)
                if interrupt_value is None:
                    break

                # Pause and wait for client approval
                session.pending_interrupt = interrupt_value
                session.status = ProjectStatus.awaiting_approval
                session.publish_event(
                    ProjectEvent(
                        event_type="approval_required",
                        data=interrupt_value,
                    )
                )

                # Block until the client submits via POST /approvals
                session.approval_event.clear()
                await session.approval_event.wait()

                # Resume with the client's decision
                resume_value = session.pending_resume_value
                session.pending_resume_value = None
                session.pending_interrupt = None
                session.status = ProjectStatus.running

                session.publish_event(
                    ProjectEvent(
                        event_type="approval_submitted",
                        data=resume_value or {},
                    )
                )

                input_val = Command(resume=resume_value)
                is_first = False

            session.status = ProjectStatus.completed
            session.publish_event(
                ProjectEvent(
                    event_type="pipeline_completed",
                    data={"project_id": session.project_id},
                )
            )

        except asyncio.CancelledError:
            session.status = ProjectStatus.cancelled
            session.publish_event(
                ProjectEvent(event_type="pipeline_cancelled")
            )
        except Exception as exc:
            logger.error("Pipeline failed for %s", session.project_id, exc_info=True)
            session.status = ProjectStatus.failed
            session.error = str(exc)
            session.publish_event(
                ProjectEvent(
                    event_type="pipeline_failed",
                    data={"error": str(exc)},
                )
            )
        finally:
            await self._cleanup_sandbox(session)

    @staticmethod
    def _stream_graph(
        session: PipelineSession,
        input_val: Any,
        run_config: dict,
    ) -> list[tuple[str, dict]]:
        """Run graph.stream() synchronously (called via to_thread).

        Returns a list of (node_name, node_output) tuples.
        """
        results: list[tuple[str, dict]] = []
        for event in session.graph.stream(
            input_val, config=run_config, stream_mode="updates"
        ):
            for node_name, node_output in event.items():
                results.append((node_name, node_output))
        return results

    @staticmethod
    def _find_interrupt(snapshot: Any) -> dict | None:
        """Extract the interrupt value from a graph state snapshot, if any."""
        if not hasattr(snapshot, "tasks") or not snapshot.tasks:
            return None
        for task in snapshot.tasks:
            if hasattr(task, "interrupts") and task.interrupts:
                return task.interrupts[0].value  # type: ignore[no-any-return]
        return None
