"""Pydantic models for API requests and responses."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """Status of a task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_APPROVAL = "needs_approval"


class ExecutionMode(str, Enum):
    """Where to execute the task."""

    LOCAL = "local"
    CLUSTER = "cluster"


class TaskRequest(BaseModel):
    """Request to create a new task."""

    prompt: str = Field(..., description="The prompt/task to send to Claude")
    session_id: str | None = Field(None, description="Optional session ID to continue")
    project: str | None = Field(None, description="Project name to work on")
    working_dir: str | None = Field(None, description="Working directory (overrides project)")
    discord_user_id: str | None = Field(None, description="Discord user ID for routing")
    target_user_id: str | None = Field(
        None,
        description="Target user's wrapper to use (for collaborative access). "
        "Must have been granted access via /share command.",
    )
    mode: ExecutionMode | None = Field(None, description="Execution mode: local or cluster")


class ApprovalOption(BaseModel):
    """An option for approval requests."""

    id: str
    label: str
    description: str | None = None


class ApprovalRequest(BaseModel):
    """A request for human approval."""

    action: str = Field(..., description="The action requiring approval")
    description: str = Field(..., description="Description of what will happen")
    options: list[ApprovalOption] = Field(default_factory=list)


class TaskResponse(BaseModel):
    """Response for task operations."""

    task_id: str = Field(..., description="Unique task identifier")
    session_id: str = Field(..., description="Session identifier for continuation")
    status: TaskStatus = Field(..., description="Current task status")
    output: str = Field(default="", description="Task output/result")
    error: str | None = Field(None, description="Error message if failed")
    approval_request: ApprovalRequest | None = Field(None, description="Pending approval request")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ApprovalSubmission(BaseModel):
    """Submission of an approval response."""

    option_id: str = Field(..., description="Selected option ID")
    custom_response: str | None = Field(None, description="Custom response if applicable")


class SessionInfo(BaseModel):
    """Information about an active session."""

    session_id: str
    task_count: int
    created_at: datetime
    last_activity: datetime
    status: str


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "healthy"
    version: str = "0.1.0"
    uptime_seconds: float = 0.0


class ProjectRequest(BaseModel):
    """Request to add a new project."""

    name: str = Field(..., description="Unique project name/alias")
    path: str = Field(..., description="Absolute path to the project directory")
    description: str = Field(default="", description="Optional project description")
    discord_user_id: str = Field(..., description="Discord user ID (owner)")


class ProjectResponse(BaseModel):
    """Response for project operations."""

    name: str
    path: str
    description: str
    owner_id: str
    created_at: datetime


# =============================================================================
# User Management Models
# =============================================================================


class RegisterLocalRequest(BaseModel):
    """Request to register a local wrapper."""

    discord_id: str = Field(..., description="Discord user ID")
    discord_name: str = Field(default="", description="Discord username")
    wrapper_url: str = Field(..., description="URL to local wrapper (e.g., http://ip:8000)")
    auth_token: str | None = Field(None, description="Optional auth token")


class EnableClusterRequest(BaseModel):
    """Request to enable cluster access for a user."""

    discord_id: str = Field(..., description="Discord user ID")
    discord_name: str = Field(default="", description="Discord username")
    storage_path: str | None = Field(None, description="Custom storage path (auto-generated if not provided)")


class UserResponse(BaseModel):
    """Response for user operations."""

    discord_id: str
    discord_name: str
    local_wrapper_url: str | None
    cluster_enabled: bool
    cluster_storage_path: str | None
    default_mode: str
    created_at: datetime
    last_seen: datetime


class SetModeRequest(BaseModel):
    """Request to set default execution mode."""

    mode: ExecutionMode = Field(..., description="Default mode: local or cluster")


# =============================================================================
# Collaborative Sharing Models
# =============================================================================


class ShareRequest(BaseModel):
    """Request to share wrapper access with another user."""

    target_user_id: str = Field(..., description="Discord ID of user to share with")


class ShareListResponse(BaseModel):
    """Response listing shared users."""

    shared_with: list[str] = Field(default_factory=list, description="List of Discord IDs")


class AccessibleWrapper(BaseModel):
    """A wrapper the user can access."""

    owner_id: str = Field(..., description="Discord ID of the wrapper owner")
    owner_name: str = Field(default="", description="Discord username of the owner")
    is_own: bool = Field(..., description="Whether this is the user's own wrapper")


class AccessibleWrappersResponse(BaseModel):
    """Response listing all wrappers a user can access."""

    wrappers: list[AccessibleWrapper] = Field(default_factory=list)
