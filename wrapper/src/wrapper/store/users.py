"""User registry for managing Discord user configurations."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class UserConfig(BaseModel):
    """Configuration for a registered user."""

    discord_id: str = Field(..., description="Discord user ID")
    discord_name: str = Field(default="", description="Discord username for display")

    # Local wrapper configuration
    local_wrapper_url: str | None = Field(None, description="URL to user's local wrapper")
    local_auth_token: str | None = Field(None, description="Auth token for local wrapper")

    # Cluster access
    cluster_enabled: bool = Field(default=False, description="Whether user can use the cluster")
    cluster_storage_path: str | None = Field(None, description="User's storage path on NFS")

    # Collaborative sharing - list of Discord user IDs allowed to use this wrapper
    shared_with: list[str] = Field(default_factory=list, description="Users allowed to use this wrapper")

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)

    # Preferences
    default_mode: str = Field(default="local", description="'local' or 'cluster'")


class UserRegistry:
    """Manages registered users with persistence."""

    def __init__(self, storage_path: Path | None = None) -> None:
        """Initialize the user registry."""
        self._users: dict[str, UserConfig] = {}
        self._storage_path = storage_path or Path.home() / ".claude-wrapper" / "users.json"
        self._load()

    def _load(self) -> None:
        """Load users from disk."""
        if self._storage_path.exists():
            try:
                with open(self._storage_path) as f:
                    data = json.load(f)
                    for discord_id, user_data in data.items():
                        self._users[discord_id] = UserConfig(**user_data)
                logger.info(f"Loaded {len(self._users)} users from {self._storage_path}")
            except Exception as e:
                logger.error(f"Failed to load users: {e}")

    def _save(self) -> None:
        """Save users to disk."""
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._storage_path, "w") as f:
                data = {
                    discord_id: user.model_dump(mode="json")
                    for discord_id, user in self._users.items()
                }
                json.dump(data, f, indent=2, default=str)
            logger.debug(f"Saved {len(self._users)} users to {self._storage_path}")
        except Exception as e:
            logger.error(f"Failed to save users: {e}")

    def register_local(
        self,
        discord_id: str,
        wrapper_url: str,
        discord_name: str = "",
        auth_token: str | None = None,
    ) -> UserConfig:
        """Register a user's local wrapper.

        Args:
            discord_id: Discord user ID
            wrapper_url: URL to user's local wrapper
            discord_name: Discord username
            auth_token: Optional auth token

        Returns:
            The user configuration
        """
        if discord_id in self._users:
            # Update existing user
            user = self._users[discord_id]
            user.local_wrapper_url = wrapper_url
            user.local_auth_token = auth_token
            user.discord_name = discord_name or user.discord_name
            user.last_seen = datetime.utcnow()
        else:
            # Create new user
            user = UserConfig(
                discord_id=discord_id,
                discord_name=discord_name,
                local_wrapper_url=wrapper_url,
                local_auth_token=auth_token,
            )
            self._users[discord_id] = user

        self._save()
        logger.info(f"Registered local wrapper for user {discord_id}: {wrapper_url}")
        return user

    def enable_cluster(
        self,
        discord_id: str,
        storage_path: str,
        discord_name: str = "",
    ) -> UserConfig:
        """Enable cluster access for a user.

        Args:
            discord_id: Discord user ID
            storage_path: Path to user's storage on NFS
            discord_name: Discord username

        Returns:
            The user configuration
        """
        if discord_id in self._users:
            user = self._users[discord_id]
            user.cluster_enabled = True
            user.cluster_storage_path = storage_path
            user.discord_name = discord_name or user.discord_name
            user.last_seen = datetime.utcnow()
        else:
            user = UserConfig(
                discord_id=discord_id,
                discord_name=discord_name,
                cluster_enabled=True,
                cluster_storage_path=storage_path,
            )
            self._users[discord_id] = user

        self._save()
        logger.info(f"Enabled cluster access for user {discord_id}: {storage_path}")
        return user

    def get(self, discord_id: str) -> UserConfig | None:
        """Get a user by Discord ID."""
        user = self._users.get(discord_id)
        if user:
            user.last_seen = datetime.utcnow()
            self._save()
        return user

    def unregister_local(self, discord_id: str) -> bool:
        """Remove local wrapper registration."""
        if discord_id in self._users:
            user = self._users[discord_id]
            user.local_wrapper_url = None
            user.local_auth_token = None
            self._save()
            return True
        return False

    def disable_cluster(self, discord_id: str) -> bool:
        """Disable cluster access for a user."""
        if discord_id in self._users:
            user = self._users[discord_id]
            user.cluster_enabled = False
            self._save()
            return True
        return False

    def remove(self, discord_id: str) -> bool:
        """Completely remove a user."""
        if discord_id in self._users:
            del self._users[discord_id]
            self._save()
            return True
        return False

    def list_all(self) -> list[UserConfig]:
        """List all registered users."""
        return list(self._users.values())

    def set_default_mode(self, discord_id: str, mode: str) -> bool:
        """Set user's default execution mode."""
        if mode not in ("local", "cluster"):
            raise ValueError("Mode must be 'local' or 'cluster'")

        if discord_id in self._users:
            self._users[discord_id].default_mode = mode
            self._save()
            return True
        return False

    # =========================================================================
    # Collaborative Sharing
    # =========================================================================

    def share_with(self, owner_id: str, target_id: str) -> bool:
        """Share wrapper access with another user.

        Args:
            owner_id: Discord ID of the wrapper owner
            target_id: Discord ID of the user to share with

        Returns:
            True if successful, False if owner not found
        """
        if owner_id not in self._users:
            return False

        user = self._users[owner_id]
        if target_id not in user.shared_with:
            user.shared_with.append(target_id)
            self._save()
            logger.info(f"User {owner_id} shared wrapper access with {target_id}")
        return True

    def unshare_with(self, owner_id: str, target_id: str) -> bool:
        """Remove wrapper sharing with another user.

        Args:
            owner_id: Discord ID of the wrapper owner
            target_id: Discord ID of the user to remove

        Returns:
            True if successful, False if owner not found or not shared
        """
        if owner_id not in self._users:
            return False

        user = self._users[owner_id]
        if target_id in user.shared_with:
            user.shared_with.remove(target_id)
            self._save()
            logger.info(f"User {owner_id} removed wrapper sharing with {target_id}")
            return True
        return False

    def get_shared_with(self, owner_id: str) -> list[str]:
        """Get list of users this wrapper is shared with.

        Args:
            owner_id: Discord ID of the wrapper owner

        Returns:
            List of Discord IDs the wrapper is shared with
        """
        if owner_id not in self._users:
            return []
        return self._users[owner_id].shared_with.copy()

    def can_access_wrapper(self, owner_id: str, requester_id: str) -> bool:
        """Check if a user can access another user's wrapper.

        Args:
            owner_id: Discord ID of the wrapper owner
            requester_id: Discord ID of the user requesting access

        Returns:
            True if requester can access the wrapper
        """
        # Users can always access their own wrapper
        if owner_id == requester_id:
            return True

        if owner_id not in self._users:
            return False

        return requester_id in self._users[owner_id].shared_with

    def get_accessible_wrappers(self, requester_id: str) -> list[UserConfig]:
        """Get all wrappers a user can access (their own + shared with them).

        Args:
            requester_id: Discord ID of the user

        Returns:
            List of UserConfigs the user can access
        """
        accessible = []
        for user in self._users.values():
            if user.discord_id == requester_id or requester_id in user.shared_with:
                if user.local_wrapper_url:  # Only include users with a wrapper
                    accessible.append(user)
        return accessible


# Singleton instance
_user_registry: UserRegistry | None = None


def get_user_registry() -> UserRegistry:
    """Get the singleton UserRegistry instance."""
    global _user_registry
    if _user_registry is None:
        _user_registry = UserRegistry()
    return _user_registry
