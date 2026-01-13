"""Task router for forwarding requests to user wrappers.

This module ensures users can ONLY interact with their own wrappers.
The routing is based on the discord_user_id from the request, which
is validated server-side by the Discord bot (cannot be spoofed).
"""

import logging
from dataclasses import dataclass
from enum import Enum

import httpx

from wrapper.api.models import (
    ApprovalSubmission,
    ExecutionMode,
    TaskRequest,
    TaskResponse,
    TaskStatus,
)
from wrapper.store.users import UserConfig, UserRegistry, get_user_registry

logger = logging.getLogger(__name__)


class RoutingError(Exception):
    """Error during task routing."""

    pass


class RoutingDecision(str, Enum):
    """Where to route a task."""

    LOCAL_WRAPPER = "local_wrapper"  # Forward to user's local wrapper
    CLUSTER = "cluster"  # Execute on Pi cluster
    REJECT = "reject"  # Cannot route - user not configured


@dataclass
class RouteResult:
    """Result of routing decision."""

    decision: RoutingDecision
    target_url: str | None = None
    auth_token: str | None = None
    error_message: str | None = None


class TaskRouter:
    """Routes tasks to appropriate execution targets.

    Security model:
    - discord_user_id comes from Discord server-side (cannot be spoofed)
    - Users can ONLY access their own registered wrapper
    - No user can send requests to another user's wrapper
    """

    def __init__(self, user_registry: UserRegistry | None = None) -> None:
        """Initialize the task router."""
        self._user_registry = user_registry or get_user_registry()
        self._http_client = httpx.AsyncClient(timeout=300.0)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._http_client.aclose()

    def _get_route(
        self,
        requester_id: str,
        target_user_id: str | None = None,
        requested_mode: ExecutionMode | None = None,
    ) -> RouteResult:
        """Determine where to route a task.

        Args:
            requester_id: Discord user ID of the requester (server-side, cannot be spoofed)
            target_user_id: Optional target user's wrapper to use (for collaborative access)
            requested_mode: Explicitly requested execution mode

        Returns:
            RouteResult with routing decision
        """
        # Determine which user's wrapper to use
        if target_user_id and target_user_id != requester_id:
            # Collaborative access - check if requester has permission
            if not self._user_registry.can_access_wrapper(target_user_id, requester_id):
                return RouteResult(
                    decision=RoutingDecision.REJECT,
                    error_message=f"You don't have access to that user's wrapper. "
                    f"Ask them to run `/share add user:@you` to grant access.",
                )
            # Use target user's wrapper
            user = self._user_registry.get(target_user_id)
            if not user:
                return RouteResult(
                    decision=RoutingDecision.REJECT,
                    error_message=f"Target user '{target_user_id}' is not registered.",
                )
        else:
            # Use requester's own wrapper
            user = self._user_registry.get(requester_id)
            if not user:
                return RouteResult(
                    decision=RoutingDecision.REJECT,
                    error_message=f"User '{requester_id}' is not registered. Use /register to set up your wrapper.",
                )

        # Determine mode: explicit request > user default
        mode = requested_mode.value if requested_mode else user.default_mode

        if mode == "local":
            if not user.local_wrapper_url:
                return RouteResult(
                    decision=RoutingDecision.REJECT,
                    error_message="No local wrapper registered. Use /register local to configure your wrapper URL.",
                )
            return RouteResult(
                decision=RoutingDecision.LOCAL_WRAPPER,
                target_url=user.local_wrapper_url,
                auth_token=user.local_auth_token,
            )

        elif mode == "cluster":
            if not user.cluster_enabled:
                return RouteResult(
                    decision=RoutingDecision.REJECT,
                    error_message="Cluster access not enabled for your account.",
                )
            return RouteResult(
                decision=RoutingDecision.CLUSTER,
                # Cluster execution handled differently (Phase 2)
            )

        return RouteResult(
            decision=RoutingDecision.REJECT,
            error_message=f"Invalid execution mode: {mode}",
        )

    async def route_task(
        self,
        request: TaskRequest,
    ) -> TaskResponse:
        """Route a task to the appropriate execution target.

        This is the main entry point for task routing. It ensures that:
        1. The user is registered
        2. The task is routed to the correct wrapper (own or shared)
        3. Collaborative access requires explicit permission

        Args:
            request: The task request (must include discord_user_id)

        Returns:
            TaskResponse from the execution target

        Raises:
            RoutingError: If routing fails or user not authorized
        """
        if not request.discord_user_id:
            raise RoutingError("discord_user_id is required for task routing")

        route = self._get_route(
            requester_id=request.discord_user_id,
            target_user_id=request.target_user_id,
            requested_mode=request.mode,
        )

        if route.decision == RoutingDecision.REJECT:
            raise RoutingError(route.error_message or "Task routing rejected")

        if route.decision == RoutingDecision.LOCAL_WRAPPER:
            return await self._forward_to_local(request, route)

        if route.decision == RoutingDecision.CLUSTER:
            # Phase 2: Cluster execution via NATS
            raise RoutingError("Cluster execution not yet implemented")

        raise RoutingError(f"Unknown routing decision: {route.decision}")

    async def _forward_to_local(
        self,
        request: TaskRequest,
        route: RouteResult,
    ) -> TaskResponse:
        """Forward a task to a user's local wrapper.

        Args:
            request: The task request
            route: The routing result with target URL

        Returns:
            TaskResponse from the local wrapper
        """
        if not route.target_url:
            raise RoutingError("No target URL for local wrapper")

        url = f"{route.target_url.rstrip('/')}/api/v1/tasks"

        # Build headers
        headers = {"Content-Type": "application/json"}
        if route.auth_token:
            headers["Authorization"] = f"Bearer {route.auth_token}"

        # Forward the request (but don't include discord_user_id in forwarded request
        # since the local wrapper doesn't need user routing)
        forward_data = {
            "prompt": request.prompt,
            "session_id": request.session_id,
            "project": request.project,
            "working_dir": request.working_dir,
            # Don't forward discord_user_id or mode - local wrapper executes directly
        }

        # Remove None values
        forward_data = {k: v for k, v in forward_data.items() if v is not None}

        logger.info(
            f"Forwarding task for user {request.discord_user_id} to {route.target_url}"
        )

        try:
            response = await self._http_client.post(
                url,
                json=forward_data,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            return TaskResponse(**data)

        except httpx.ConnectError as e:
            logger.error(f"Failed to connect to local wrapper: {e}")
            raise RoutingError(
                f"Cannot connect to your local wrapper at {route.target_url}. "
                "Is it running?"
            )
        except httpx.HTTPStatusError as e:
            logger.error(f"Local wrapper returned error: {e}")
            raise RoutingError(f"Local wrapper error: {e.response.text}")
        except Exception as e:
            logger.error(f"Unexpected error forwarding task: {e}")
            raise RoutingError(f"Failed to forward task: {e}")

    async def route_approval(
        self,
        user_id: str,
        task_id: str,
        submission: ApprovalSubmission,
        mode: ExecutionMode | None = None,
    ) -> TaskResponse:
        """Route an approval submission to the appropriate target.

        Args:
            user_id: Discord user ID
            task_id: Task ID to approve
            submission: Approval submission
            mode: Execution mode

        Returns:
            TaskResponse from the execution target
        """
        if not user_id:
            raise RoutingError("discord_user_id is required for approval routing")

        route = self._get_route(user_id, mode)

        if route.decision == RoutingDecision.REJECT:
            raise RoutingError(route.error_message or "Approval routing rejected")

        if route.decision == RoutingDecision.LOCAL_WRAPPER:
            return await self._forward_approval_to_local(
                user_id, task_id, submission, route
            )

        if route.decision == RoutingDecision.CLUSTER:
            raise RoutingError("Cluster execution not yet implemented")

        raise RoutingError(f"Unknown routing decision: {route.decision}")

    async def _forward_approval_to_local(
        self,
        user_id: str,
        task_id: str,
        submission: ApprovalSubmission,
        route: RouteResult,
    ) -> TaskResponse:
        """Forward an approval to a user's local wrapper."""
        if not route.target_url:
            raise RoutingError("No target URL for local wrapper")

        url = f"{route.target_url.rstrip('/')}/api/v1/tasks/{task_id}/approve"

        headers = {"Content-Type": "application/json"}
        if route.auth_token:
            headers["Authorization"] = f"Bearer {route.auth_token}"

        logger.info(f"Forwarding approval for user {user_id} to {route.target_url}")

        try:
            response = await self._http_client.post(
                url,
                json=submission.model_dump(),
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            return TaskResponse(**data)

        except httpx.ConnectError as e:
            raise RoutingError(
                f"Cannot connect to your local wrapper at {route.target_url}. "
                "Is it running?"
            )
        except httpx.HTTPStatusError as e:
            raise RoutingError(f"Local wrapper error: {e.response.text}")
        except Exception as e:
            raise RoutingError(f"Failed to forward approval: {e}")

    async def route_get_task(
        self,
        user_id: str,
        task_id: str,
        mode: ExecutionMode | None = None,
    ) -> TaskResponse:
        """Route a task status request to the appropriate target.

        Args:
            user_id: Discord user ID
            task_id: Task ID to check
            mode: Execution mode

        Returns:
            TaskResponse from the execution target
        """
        if not user_id:
            raise RoutingError("discord_user_id is required")

        route = self._get_route(user_id, mode)

        if route.decision == RoutingDecision.REJECT:
            raise RoutingError(route.error_message or "Routing rejected")

        if route.decision == RoutingDecision.LOCAL_WRAPPER:
            return await self._forward_get_task_to_local(user_id, task_id, route)

        if route.decision == RoutingDecision.CLUSTER:
            raise RoutingError("Cluster execution not yet implemented")

        raise RoutingError(f"Unknown routing decision: {route.decision}")

    async def _forward_get_task_to_local(
        self,
        user_id: str,
        task_id: str,
        route: RouteResult,
    ) -> TaskResponse:
        """Forward a task status request to a user's local wrapper."""
        if not route.target_url:
            raise RoutingError("No target URL for local wrapper")

        url = f"{route.target_url.rstrip('/')}/api/v1/tasks/{task_id}"

        headers = {}
        if route.auth_token:
            headers["Authorization"] = f"Bearer {route.auth_token}"

        try:
            response = await self._http_client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            return TaskResponse(**data)

        except httpx.ConnectError as e:
            raise RoutingError(
                f"Cannot connect to your local wrapper at {route.target_url}. "
                "Is it running?"
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise RoutingError(f"Task {task_id} not found on your local wrapper")
            raise RoutingError(f"Local wrapper error: {e.response.text}")
        except Exception as e:
            raise RoutingError(f"Failed to get task status: {e}")


# Singleton instance
_task_router: TaskRouter | None = None


def get_task_router() -> TaskRouter:
    """Get the singleton TaskRouter instance."""
    global _task_router
    if _task_router is None:
        _task_router = TaskRouter()
    return _task_router
