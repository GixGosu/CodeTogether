"""Project registry for managing named projects with per-user isolation."""

import json
import logging
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from wrapper.config import settings

logger = logging.getLogger(__name__)


class Project(BaseModel):
    """A registered project."""

    name: str = Field(..., description="Project name/alias (without user prefix)")
    path: str = Field(..., description="Absolute path to the project directory")
    description: str = Field(default="", description="Optional project description")
    owner_id: str = Field(..., description="Discord user ID who owns this project")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProjectRegistry:
    """Manages registered projects with per-user isolation and persistence.

    Projects are namespaced by user ID to prevent cross-user access.
    Internal key format: "{user_id}:{project_name}"
    """

    def __init__(self, storage_path: Path | None = None) -> None:
        """Initialize the project registry."""
        self._projects: dict[str, Project] = {}
        self._storage_path = storage_path or Path.home() / ".claude-wrapper" / "projects.json"
        self._load()

    def _make_key(self, user_id: str, name: str) -> str:
        """Create internal key from user ID and project name."""
        return f"{user_id}:{name.lower().strip()}"

    def _load(self) -> None:
        """Load projects from disk."""
        if self._storage_path.exists():
            try:
                with open(self._storage_path) as f:
                    data = json.load(f)
                    for key, proj_data in data.items():
                        self._projects[key] = Project(**proj_data)
                logger.info(f"Loaded {len(self._projects)} projects from {self._storage_path}")
            except Exception as e:
                logger.error(f"Failed to load projects: {e}")

    def _save(self) -> None:
        """Save projects to disk."""
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._storage_path, "w") as f:
                data = {key: proj.model_dump(mode="json") for key, proj in self._projects.items()}
                json.dump(data, f, indent=2, default=str)
            logger.debug(f"Saved {len(self._projects)} projects to {self._storage_path}")
        except Exception as e:
            logger.error(f"Failed to save projects: {e}")

    def add(
        self,
        user_id: str,
        name: str,
        path: str,
        description: str = "",
    ) -> Project:
        """Add a new project for a user.

        Args:
            user_id: Discord user ID (owner)
            name: Project name/alias
            path: Absolute path to the project directory
            description: Optional description

        Returns:
            The created Project

        Raises:
            ValueError: If name already exists for this user or path is invalid
        """
        name = name.lower().strip()
        key = self._make_key(user_id, name)

        if key in self._projects:
            raise ValueError(f"Project '{name}' already exists for your account")

        # Validate path exists
        project_path = Path(path).expanduser().resolve()
        if not project_path.exists():
            raise ValueError(f"Path does not exist: {path}")
        if not project_path.is_dir():
            raise ValueError(f"Path is not a directory: {path}")

        # Security: Validate path is within allowed directories
        if not settings.is_path_allowed(project_path):
            allowed = settings.get_allowed_project_dirs()
            allowed_str = ", ".join(str(d) for d in allowed) if allowed else "none configured"
            raise ValueError(
                f"Path '{project_path}' is not within allowed directories. "
                f"Allowed: {allowed_str}"
            )

        project = Project(
            name=name,
            path=str(project_path),
            description=description,
            owner_id=user_id,
        )

        self._projects[key] = project
        self._save()
        logger.info(f"Added project for user {user_id}: {name} -> {project_path}")
        return project

    def get(self, user_id: str, name: str) -> Project | None:
        """Get a project by name for a specific user.

        Args:
            user_id: Discord user ID
            name: Project name

        Returns:
            Project or None if not found
        """
        key = self._make_key(user_id, name)
        return self._projects.get(key)

    def remove(self, user_id: str, name: str) -> bool:
        """Remove a project for a user.

        Args:
            user_id: Discord user ID
            name: Project name

        Returns:
            True if removed, False if not found
        """
        key = self._make_key(user_id, name)
        if key in self._projects:
            # Verify ownership
            project = self._projects[key]
            if project.owner_id != user_id:
                logger.warning(f"User {user_id} attempted to remove project owned by {project.owner_id}")
                return False
            del self._projects[key]
            self._save()
            logger.info(f"Removed project for user {user_id}: {name}")
            return True
        return False

    def list_for_user(self, user_id: str) -> list[Project]:
        """List all projects for a specific user.

        Args:
            user_id: Discord user ID

        Returns:
            List of projects owned by this user
        """
        return [
            proj for proj in self._projects.values()
            if proj.owner_id == user_id
        ]

    def list_all(self) -> list[Project]:
        """List all registered projects (admin only).

        Returns:
            List of all projects
        """
        return list(self._projects.values())

    def get_path(self, user_id: str, name: str) -> Path | None:
        """Get the path for a user's project.

        Args:
            user_id: Discord user ID
            name: Project name

        Returns:
            Path or None if not found
        """
        project = self.get(user_id, name)
        if project:
            return Path(project.path)
        return None


# Singleton instance
_project_registry: ProjectRegistry | None = None


def get_project_registry() -> ProjectRegistry:
    """Get the singleton ProjectRegistry instance."""
    global _project_registry
    if _project_registry is None:
        _project_registry = ProjectRegistry()
    return _project_registry
