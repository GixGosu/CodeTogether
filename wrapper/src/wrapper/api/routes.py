"""API routes for the wrapper service."""

import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from wrapper.api.models import (
    AccessibleWrapper,
    AccessibleWrappersResponse,
    ApprovalSubmission,
    EnableClusterRequest,
    HealthResponse,
    ProjectRequest,
    ProjectResponse,
    RegisterLocalRequest,
    SessionInfo,
    SetModeRequest,
    ShareListResponse,
    ShareRequest,
    TaskRequest,
    TaskResponse,
    TaskStatus,
    UserResponse,
)
from wrapper.claude.session import SessionManager, get_session_manager
from wrapper.config import settings
from wrapper.routing.router import RoutingError, TaskRouter, get_task_router
from wrapper.store.projects import ProjectRegistry, get_project_registry
from wrapper.store.sessions import TaskStore, get_task_store
from wrapper.store.users import UserRegistry, get_user_registry

router = APIRouter()

# Track service start time for uptime
_start_time = time.time()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version="0.1.0",
        uptime_seconds=time.time() - _start_time,
    )


# =============================================================================
# Project Management (Per-User Isolation)
# =============================================================================


@router.get("/projects/{discord_user_id}", response_model=list[ProjectResponse])
async def list_user_projects(
    discord_user_id: str,
    registry: Annotated[ProjectRegistry, Depends(get_project_registry)],
) -> list[ProjectResponse]:
    """List all projects for a specific user."""
    projects = registry.list_for_user(discord_user_id)
    return [
        ProjectResponse(
            name=p.name,
            path=p.path,
            description=p.description,
            owner_id=p.owner_id,
            created_at=p.created_at,
        )
        for p in projects
    ]


@router.post("/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def add_project(
    request: ProjectRequest,
    registry: Annotated[ProjectRegistry, Depends(get_project_registry)],
) -> ProjectResponse:
    """Add a new project for a user."""
    try:
        project = registry.add(
            user_id=request.discord_user_id,
            name=request.name,
            path=request.path,
            description=request.description,
        )
        return ProjectResponse(
            name=project.name,
            path=project.path,
            description=project.description,
            owner_id=project.owner_id,
            created_at=project.created_at,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/projects/{discord_user_id}/{name}", response_model=ProjectResponse)
async def get_project(
    discord_user_id: str,
    name: str,
    registry: Annotated[ProjectRegistry, Depends(get_project_registry)],
) -> ProjectResponse:
    """Get a project by name for a specific user."""
    project = registry.get(discord_user_id, name)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{name}' not found",
        )
    return ProjectResponse(
        name=project.name,
        path=project.path,
        description=project.description,
        owner_id=project.owner_id,
        created_at=project.created_at,
    )


@router.delete("/projects/{discord_user_id}/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_project(
    discord_user_id: str,
    name: str,
    registry: Annotated[ProjectRegistry, Depends(get_project_registry)],
) -> None:
    """Remove a project for a user."""
    if not registry.remove(discord_user_id, name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{name}' not found",
        )


# =============================================================================
# Task Management
# =============================================================================


@router.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    request: TaskRequest,
    session_manager: Annotated[SessionManager, Depends(get_session_manager)],
    task_store: Annotated[TaskStore, Depends(get_task_store)],
    registry: Annotated[ProjectRegistry, Depends(get_project_registry)],
    task_router: Annotated[TaskRouter, Depends(get_task_router)],
) -> TaskResponse:
    """Create and execute a new task.

    In orchestrator mode: Routes to user's own wrapper (per-user isolation enforced).
    In local mode: Executes directly on this machine.
    """
    # ORCHESTRATOR MODE: Route to user's wrapper
    # This ensures users can ONLY interact with their own wrappers
    if settings.is_orchestrator:
        if not request.discord_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="discord_user_id is required in orchestrator mode",
            )
        try:
            return await task_router.route_task(request)
        except RoutingError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    # LOCAL MODE: Execute directly on this machine
    # Resolve working directory from project (working_dir is ignored for security)
    working_dir = None

    # Look up project path (per-user isolation)
    if request.project:
        if not request.discord_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="discord_user_id is required when specifying a project",
            )
        # Look up project for THIS user only
        project = registry.get(request.discord_user_id, request.project)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project '{request.project}' not found. Use /project list to see your projects.",
            )
        working_dir = project.path

        # Additional security: Re-validate path is still allowed
        # (in case allowed_project_dirs changed after project was registered)
        if not settings.is_path_allowed(Path(working_dir)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Project path is no longer within allowed directories. Please re-register the project.",
            )

    # Create or get session
    session = await session_manager.get_or_create_session(
        session_id=request.session_id,
        working_dir=working_dir,
    )

    # Create task record
    task = task_store.create_task(session_id=session.session_id)

    # Execute the task asynchronously
    try:
        task_store.update_task(task.task_id, status=TaskStatus.RUNNING)
        result = await session_manager.execute_task(session.session_id, request.prompt)

        # Update task with result
        task_store.update_task(
            task.task_id,
            status=result.status,
            output=result.output,
            error=result.error,
            approval_request=result.approval_request,
        )

        return task_store.get_task(task.task_id)
    except Exception as e:
        task_store.update_task(task.task_id, status=TaskStatus.FAILED, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Task execution failed: {e}",
        )


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    task_store: Annotated[TaskStore, Depends(get_task_store)],
    task_router: Annotated[TaskRouter, Depends(get_task_router)],
    discord_user_id: str | None = None,
) -> TaskResponse:
    """Get task status and result.

    In orchestrator mode: Routes to user's own wrapper.
    In local mode: Looks up in local task store.
    """
    # ORCHESTRATOR MODE: Route to user's wrapper
    if settings.is_orchestrator:
        if not discord_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="discord_user_id query parameter is required in orchestrator mode",
            )
        try:
            return await task_router.route_get_task(discord_user_id, task_id)
        except RoutingError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    # LOCAL MODE: Look up in local store
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )
    return task


@router.post("/tasks/{task_id}/approve", response_model=TaskResponse)
async def submit_approval(
    task_id: str,
    submission: ApprovalSubmission,
    session_manager: Annotated[SessionManager, Depends(get_session_manager)],
    task_store: Annotated[TaskStore, Depends(get_task_store)],
    task_router: Annotated[TaskRouter, Depends(get_task_router)],
    discord_user_id: str | None = None,
) -> TaskResponse:
    """Submit approval for a task requiring human intervention.

    In orchestrator mode: Routes to user's own wrapper.
    In local mode: Processes approval locally.
    """
    # ORCHESTRATOR MODE: Route to user's wrapper
    if settings.is_orchestrator:
        if not discord_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="discord_user_id query parameter is required in orchestrator mode",
            )
        try:
            return await task_router.route_approval(
                discord_user_id, task_id, submission
            )
        except RoutingError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    # LOCAL MODE: Process approval locally
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )

    if task.status != TaskStatus.NEEDS_APPROVAL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Task {task_id} is not awaiting approval",
        )

    # Process approval and continue task
    try:
        task_store.update_task(task_id, status=TaskStatus.RUNNING)
        result = await session_manager.submit_approval(
            task.session_id,
            submission.option_id,
            submission.custom_response,
        )

        task_store.update_task(
            task_id,
            status=result.status,
            output=task.output + "\n" + result.output,
            error=result.error,
            approval_request=result.approval_request,
        )

        return task_store.get_task(task_id)
    except Exception as e:
        task_store.update_task(task_id, status=TaskStatus.FAILED, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Approval processing failed: {e}",
        )


# =============================================================================
# Session Management
# =============================================================================


@router.get("/sessions", response_model=list[SessionInfo])
async def list_sessions(
    session_manager: Annotated[SessionManager, Depends(get_session_manager)],
) -> list[SessionInfo]:
    """List all active sessions."""
    return await session_manager.list_sessions()


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def terminate_session(
    session_id: str,
    session_manager: Annotated[SessionManager, Depends(get_session_manager)],
) -> None:
    """Terminate an active session."""
    success = await session_manager.terminate_session(session_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )


# =============================================================================
# User Management
# =============================================================================


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    registry: Annotated[UserRegistry, Depends(get_user_registry)],
) -> list[UserResponse]:
    """List all registered users."""
    users = registry.list_all()
    return [
        UserResponse(
            discord_id=u.discord_id,
            discord_name=u.discord_name,
            local_wrapper_url=u.local_wrapper_url,
            cluster_enabled=u.cluster_enabled,
            cluster_storage_path=u.cluster_storage_path,
            default_mode=u.default_mode,
            created_at=u.created_at,
            last_seen=u.last_seen,
        )
        for u in users
    ]


@router.get("/users/{discord_id}", response_model=UserResponse)
async def get_user(
    discord_id: str,
    registry: Annotated[UserRegistry, Depends(get_user_registry)],
) -> UserResponse:
    """Get a user by Discord ID."""
    user = registry.get(discord_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{discord_id}' not found",
        )
    return UserResponse(
        discord_id=user.discord_id,
        discord_name=user.discord_name,
        local_wrapper_url=user.local_wrapper_url,
        cluster_enabled=user.cluster_enabled,
        cluster_storage_path=user.cluster_storage_path,
        default_mode=user.default_mode,
        created_at=user.created_at,
        last_seen=user.last_seen,
    )


@router.post("/users/register-local", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_local_wrapper(
    request: RegisterLocalRequest,
    registry: Annotated[UserRegistry, Depends(get_user_registry)],
) -> UserResponse:
    """Register a user's local wrapper."""
    user = registry.register_local(
        discord_id=request.discord_id,
        wrapper_url=request.wrapper_url,
        discord_name=request.discord_name,
        auth_token=request.auth_token,
    )
    return UserResponse(
        discord_id=user.discord_id,
        discord_name=user.discord_name,
        local_wrapper_url=user.local_wrapper_url,
        cluster_enabled=user.cluster_enabled,
        cluster_storage_path=user.cluster_storage_path,
        default_mode=user.default_mode,
        created_at=user.created_at,
        last_seen=user.last_seen,
    )


@router.post("/users/enable-cluster", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def enable_cluster_access(
    request: EnableClusterRequest,
    registry: Annotated[UserRegistry, Depends(get_user_registry)],
) -> UserResponse:
    """Enable cluster access for a user."""
    # Auto-generate storage path if not provided
    storage_path = request.storage_path or f"/nfs/users/{request.discord_id}"

    user = registry.enable_cluster(
        discord_id=request.discord_id,
        storage_path=storage_path,
        discord_name=request.discord_name,
    )
    return UserResponse(
        discord_id=user.discord_id,
        discord_name=user.discord_name,
        local_wrapper_url=user.local_wrapper_url,
        cluster_enabled=user.cluster_enabled,
        cluster_storage_path=user.cluster_storage_path,
        default_mode=user.default_mode,
        created_at=user.created_at,
        last_seen=user.last_seen,
    )


@router.post("/users/{discord_id}/set-mode", response_model=UserResponse)
async def set_default_mode(
    discord_id: str,
    request: SetModeRequest,
    registry: Annotated[UserRegistry, Depends(get_user_registry)],
) -> UserResponse:
    """Set user's default execution mode."""
    if not registry.set_default_mode(discord_id, request.mode.value):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{discord_id}' not found",
        )
    user = registry.get(discord_id)
    return UserResponse(
        discord_id=user.discord_id,
        discord_name=user.discord_name,
        local_wrapper_url=user.local_wrapper_url,
        cluster_enabled=user.cluster_enabled,
        cluster_storage_path=user.cluster_storage_path,
        default_mode=user.default_mode,
        created_at=user.created_at,
        last_seen=user.last_seen,
    )


@router.delete("/users/{discord_id}/local", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_local_wrapper(
    discord_id: str,
    registry: Annotated[UserRegistry, Depends(get_user_registry)],
) -> None:
    """Unregister a user's local wrapper."""
    if not registry.unregister_local(discord_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{discord_id}' not found",
        )


@router.delete("/users/{discord_id}/cluster", status_code=status.HTTP_204_NO_CONTENT)
async def disable_cluster_access(
    discord_id: str,
    registry: Annotated[UserRegistry, Depends(get_user_registry)],
) -> None:
    """Disable cluster access for a user."""
    if not registry.disable_cluster(discord_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{discord_id}' not found",
        )


@router.delete("/users/{discord_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_user(
    discord_id: str,
    registry: Annotated[UserRegistry, Depends(get_user_registry)],
) -> None:
    """Completely remove a user."""
    if not registry.remove(discord_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{discord_id}' not found",
        )


# =============================================================================
# Collaborative Sharing
# =============================================================================


@router.post("/users/{discord_id}/share", status_code=status.HTTP_201_CREATED)
async def share_wrapper(
    discord_id: str,
    request: ShareRequest,
    registry: Annotated[UserRegistry, Depends(get_user_registry)],
) -> ShareListResponse:
    """Share wrapper access with another user.

    The owner (discord_id) grants access to target_user_id.
    """
    if not registry.share_with(discord_id, request.target_user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{discord_id}' not found",
        )
    return ShareListResponse(shared_with=registry.get_shared_with(discord_id))


@router.delete("/users/{discord_id}/share/{target_id}", status_code=status.HTTP_200_OK)
async def unshare_wrapper(
    discord_id: str,
    target_id: str,
    registry: Annotated[UserRegistry, Depends(get_user_registry)],
) -> ShareListResponse:
    """Remove wrapper sharing with another user."""
    if not registry.unshare_with(discord_id, target_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{discord_id}' not found or not shared with '{target_id}'",
        )
    return ShareListResponse(shared_with=registry.get_shared_with(discord_id))


@router.get("/users/{discord_id}/share", response_model=ShareListResponse)
async def list_shared_users(
    discord_id: str,
    registry: Annotated[UserRegistry, Depends(get_user_registry)],
) -> ShareListResponse:
    """List users this wrapper is shared with."""
    user = registry.get(discord_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{discord_id}' not found",
        )
    return ShareListResponse(shared_with=registry.get_shared_with(discord_id))


@router.get("/users/{discord_id}/accessible-wrappers", response_model=AccessibleWrappersResponse)
async def list_accessible_wrappers(
    discord_id: str,
    registry: Annotated[UserRegistry, Depends(get_user_registry)],
) -> AccessibleWrappersResponse:
    """List all wrappers a user can access (their own + shared with them)."""
    accessible = registry.get_accessible_wrappers(discord_id)
    return AccessibleWrappersResponse(
        wrappers=[
            AccessibleWrapper(
                owner_id=u.discord_id,
                owner_name=u.discord_name,
                is_own=(u.discord_id == discord_id),
            )
            for u in accessible
        ]
    )
