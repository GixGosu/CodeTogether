"""Session management for Claude Code instances."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from wrapper.api.models import ApprovalRequest, SessionInfo, TaskStatus
from wrapper.claude.executor import ClaudeExecutor, ExecutionResult
from wrapper.config import settings

logger = logging.getLogger(__name__)


@dataclass
class Session:
    """Represents a Claude Code session."""

    session_id: str
    working_dir: Path
    executor: ClaudeExecutor
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)
    task_count: int = 0
    status: str = "active"


class SessionManager:
    """Manages Claude Code sessions."""

    def __init__(self) -> None:
        """Initialize the session manager."""
        self._sessions: dict[str, Session] = {}
        self._base_dir = Path(settings.claude_working_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    async def get_or_create_session(
        self,
        session_id: str | None = None,
        working_dir: str | None = None,
    ) -> Session:
        """
        Get an existing session or create a new one.

        Args:
            session_id: Optional existing session ID to retrieve
            working_dir: Optional working directory override

        Returns:
            Session instance
        """
        # Return existing session if ID provided and exists
        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
            session.last_activity = datetime.utcnow()
            return session

        # Create new session
        new_id = session_id or str(uuid4())
        work_dir = Path(working_dir) if working_dir else self._base_dir / new_id

        # Only pass API key env var if configured (CLI uses its own auth via `claude login`)
        env = {}
        if settings.anthropic_api_key:
            env["ANTHROPIC_API_KEY"] = settings.anthropic_api_key

        executor = ClaudeExecutor(
            working_dir=work_dir,
            env=env,
        )

        session = Session(
            session_id=new_id,
            working_dir=work_dir,
            executor=executor,
        )

        self._sessions[new_id] = session
        logger.info(f"Created new session: {new_id}")
        return session

    async def execute_task(self, session_id: str, prompt: str) -> ExecutionResult:
        """
        Execute a task in the specified session.

        Args:
            session_id: The session to use
            prompt: The task prompt

        Returns:
            ExecutionResult with the execution outcome
        """
        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")

        session = self._sessions[session_id]
        session.last_activity = datetime.utcnow()
        session.task_count += 1

        # Execute via the session's executor
        result = await session.executor.execute(
            prompt=prompt,
            session_id=session_id if session.task_count > 1 else None,
        )

        # Update session state based on result
        if result.status == TaskStatus.FAILED:
            session.status = "error"
        elif result.status == TaskStatus.NEEDS_APPROVAL:
            session.status = "awaiting_approval"
        else:
            session.status = "active"

        return result

    async def submit_approval(
        self,
        session_id: str,
        option_id: str,
        custom_response: str | None = None,
    ) -> ExecutionResult:
        """
        Submit an approval response for a session.

        Args:
            session_id: The session awaiting approval
            option_id: The selected option
            custom_response: Optional custom response

        Returns:
            ExecutionResult with the continuation outcome
        """
        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")

        session = self._sessions[session_id]
        session.last_activity = datetime.utcnow()

        result = await session.executor.submit_approval(
            session_id=session_id,
            option_id=option_id,
            custom_response=custom_response,
        )

        # Update session status
        if result.status == TaskStatus.NEEDS_APPROVAL:
            session.status = "awaiting_approval"
        elif result.status == TaskStatus.FAILED:
            session.status = "error"
        else:
            session.status = "active"

        return result

    async def list_sessions(self) -> list[SessionInfo]:
        """List all active sessions."""
        return [
            SessionInfo(
                session_id=s.session_id,
                task_count=s.task_count,
                created_at=s.created_at,
                last_activity=s.last_activity,
                status=s.status,
            )
            for s in self._sessions.values()
        ]

    async def terminate_session(self, session_id: str) -> bool:
        """
        Terminate a session.

        Args:
            session_id: The session to terminate

        Returns:
            True if terminated, False if not found
        """
        if session_id not in self._sessions:
            return False

        session = self._sessions.pop(session_id)
        session.status = "terminated"
        logger.info(f"Terminated session: {session_id}")
        return True

    async def cleanup_stale_sessions(self, max_age_hours: int = 24) -> int:
        """
        Clean up sessions that have been inactive.

        Args:
            max_age_hours: Maximum age in hours before cleanup

        Returns:
            Number of sessions cleaned up
        """
        now = datetime.utcnow()
        stale_ids = [
            sid
            for sid, session in self._sessions.items()
            if (now - session.last_activity).total_seconds() > max_age_hours * 3600
        ]

        for sid in stale_ids:
            await self.terminate_session(sid)

        return len(stale_ids)


# Singleton instance
_session_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    """Get the singleton SessionManager instance."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
