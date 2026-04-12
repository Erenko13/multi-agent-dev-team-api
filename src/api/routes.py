from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from src.api.dependencies import get_session_manager
from src.api.schemas import (
    ApprovalRequest,
    ApprovalResponse,
    CreateProjectRequest,
    PendingApproval,
    ProjectDetail,
    ProjectStatus,
    ProjectSummary,
)
from src.api.sessions import SessionManager
from src.utils.container import DockerSandbox

router = APIRouter()


# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------


@router.get("/health")
async def health_check(
    manager: SessionManager = Depends(get_session_manager),
) -> dict[str, Any]:
    docker_available = DockerSandbox.is_docker_available()
    return {
        "status": "ok",
        "docker_available": docker_available,
        "available_slots": manager.available_slots(),
        "total_slots": 5,
    }


# ------------------------------------------------------------------
# Projects
# ------------------------------------------------------------------


@router.post("/projects", status_code=201, response_model=ProjectDetail)
async def create_project(
    request: Request,
    body: CreateProjectRequest,
    manager: SessionManager = Depends(get_session_manager),
) -> ProjectDetail:
    try:
        session = await manager.create_session(
            requirements=body.requirements,
            use_sandbox=body.use_sandbox,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    manager.start_pipeline(session.project_id)

    base = str(request.base_url).rstrip("/")
    project_url = f"{base}/api/projects/{session.project_id}"
    events_url = f"{project_url}/events"

    return ProjectDetail(
        project_id=session.project_id,
        status=session.status,
        created_at=session.created_at,
        current_agent=None,
        requirements=session.requirements,
        workspace_path=session.workspace_path,
        project_url=project_url,
        events_url=events_url,
    )


@router.get("/projects", response_model=list[ProjectSummary])
async def list_projects(
    status: ProjectStatus | None = Query(None),
    manager: SessionManager = Depends(get_session_manager),
) -> list[ProjectSummary]:
    sessions = manager.list_sessions(status=status)
    return [
        ProjectSummary(
            project_id=s.project_id,
            status=s.status,
            created_at=s.created_at,
            current_agent=None,
            requirements=s.requirements,
        )
        for s in sessions
    ]


@router.get("/projects/{project_id}", response_model=ProjectDetail)
async def get_project(
    project_id: str,
    request: Request,
    manager: SessionManager = Depends(get_session_manager),
) -> ProjectDetail:
    session = manager.get_session(project_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Project not found")

    state = manager.get_state_snapshot(project_id)
    base = str(request.base_url).rstrip("/")
    project_url = f"{base}/api/projects/{project_id}"

    return ProjectDetail(
        project_id=state.get("project_id", project_id),
        status=state.get("status", session.status),
        created_at=state.get("created_at", session.created_at),
        current_agent=state.get("current_agent") or None,
        requirements=state.get("requirements", session.requirements),
        workspace_path=state.get("workspace_path", session.workspace_path),
        project_url=project_url,
        events_url=f"{project_url}/events",
        user_stories=state.get("user_stories", []),
        task_plan=state.get("task_plan", []),
        architecture_doc=state.get("architecture_doc", ""),
        folder_structure=state.get("folder_structure", []),
        tech_stack=state.get("tech_stack", {}),
        generated_files=state.get("generated_files", []),
        review_comments=state.get("review_comments", []),
        test_results=state.get("test_results", []),
        tests_passing=state.get("tests_passing", False),
        review_iteration=state.get("review_iteration", 0),
        error=state.get("error") or None,
        pending_approval=state.get("pending_approval"),
    )


@router.delete("/projects/{project_id}", status_code=204)
async def cancel_project(
    project_id: str,
    manager: SessionManager = Depends(get_session_manager),
) -> None:
    session = manager.get_session(project_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await manager.cancel_session(project_id)


# ------------------------------------------------------------------
# Approvals
# ------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/approvals/pending",
    response_model=PendingApproval | None,
)
async def get_pending_approval(
    project_id: str,
    manager: SessionManager = Depends(get_session_manager),
) -> PendingApproval | None:
    session = manager.get_session(project_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Project not found")

    state = manager.get_state_snapshot(project_id)
    return state.get("pending_approval")


@router.post(
    "/projects/{project_id}/approvals",
    response_model=ApprovalResponse,
)
async def submit_approval(
    project_id: str,
    body: ApprovalRequest,
    manager: SessionManager = Depends(get_session_manager),
) -> ApprovalResponse:
    session = manager.get_session(project_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Project not found")

    resumed = await manager.submit_approval(
        project_id=project_id,
        approved=body.approved,
        feedback=body.feedback,
    )
    if not resumed:
        raise HTTPException(
            status_code=409, detail="No pending approval for this project"
        )
    return ApprovalResponse(
        project_id=project_id,
        approved=body.approved,
        resumed=True,
    )


# ------------------------------------------------------------------
# SSE Events
# ------------------------------------------------------------------


@router.get("/projects/{project_id}/events")
async def stream_events(
    project_id: str,
    manager: SessionManager = Depends(get_session_manager),
) -> StreamingResponse:
    session = manager.get_session(project_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Project not found")

    q, _ = manager.subscribe_events(project_id)

    async def event_generator():
        event_id = 0
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30)
                    event_id += 1
                    yield (
                        f"id: {event_id}\n"
                        f"event: {event.event_type}\n"
                        f"data: {event.model_dump_json()}\n\n"
                    )
                    if event.event_type in (
                        "pipeline_completed",
                        "pipeline_failed",
                        "pipeline_cancelled",
                    ):
                        break
                except asyncio.TimeoutError:
                    # Keep-alive comment to prevent proxy/client timeouts
                    yield ": keepalive\n\n"
        finally:
            manager.unsubscribe_events(project_id, q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
