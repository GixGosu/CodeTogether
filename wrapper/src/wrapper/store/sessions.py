"""In-memory task storage (Phase 1). Will be replaced with Redis in Phase 2."""

from datetime import datetime
from uuid import uuid4

from wrapper.api.models import ApprovalRequest, TaskResponse, TaskStatus


class TaskStore:
    """In-memory storage for tasks."""

    def __init__(self) -> None:
        """Initialize the task store."""
        self._tasks: dict[str, TaskResponse] = {}

    def create_task(self, session_id: str) -> TaskResponse:
        """
        Create a new task record.

        Args:
            session_id: The session this task belongs to

        Returns:
            The created TaskResponse
        """
        task_id = str(uuid4())
        now = datetime.utcnow()

        task = TaskResponse(
            task_id=task_id,
            session_id=session_id,
            status=TaskStatus.PENDING,
            output="",
            created_at=now,
            updated_at=now,
        )

        self._tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> TaskResponse | None:
        """
        Get a task by ID.

        Args:
            task_id: The task ID

        Returns:
            TaskResponse or None if not found
        """
        return self._tasks.get(task_id)

    def update_task(
        self,
        task_id: str,
        *,
        status: TaskStatus | None = None,
        output: str | None = None,
        error: str | None = None,
        approval_request: ApprovalRequest | None = None,
    ) -> TaskResponse | None:
        """
        Update a task record.

        Args:
            task_id: The task ID
            status: New status
            output: New output
            error: Error message
            approval_request: Approval request if needs_approval

        Returns:
            Updated TaskResponse or None if not found
        """
        task = self._tasks.get(task_id)
        if not task:
            return None

        # Create updated task (Pydantic models are immutable by default)
        update_data = {"updated_at": datetime.utcnow()}

        if status is not None:
            update_data["status"] = status
        if output is not None:
            update_data["output"] = output
        if error is not None:
            update_data["error"] = error
        if approval_request is not None:
            update_data["approval_request"] = approval_request

        updated_task = task.model_copy(update=update_data)
        self._tasks[task_id] = updated_task
        return updated_task

    def list_tasks(self, session_id: str | None = None) -> list[TaskResponse]:
        """
        List tasks, optionally filtered by session.

        Args:
            session_id: Optional session filter

        Returns:
            List of TaskResponse objects
        """
        tasks = list(self._tasks.values())
        if session_id:
            tasks = [t for t in tasks if t.session_id == session_id]
        return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    def delete_task(self, task_id: str) -> bool:
        """
        Delete a task.

        Args:
            task_id: The task ID

        Returns:
            True if deleted, False if not found
        """
        if task_id in self._tasks:
            del self._tasks[task_id]
            return True
        return False


# Singleton instance
_task_store: TaskStore | None = None


def get_task_store() -> TaskStore:
    """Get the singleton TaskStore instance."""
    global _task_store
    if _task_store is None:
        _task_store = TaskStore()
    return _task_store
