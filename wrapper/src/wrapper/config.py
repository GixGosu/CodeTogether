"""Configuration management for the wrapper service."""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Service Mode
    # - "orchestrator": Central orchestrator that routes tasks to user wrappers
    # - "local": Local wrapper that executes tasks directly (runs on user's machine)
    service_mode: str = "local"

    # Claude
    anthropic_api_key: str = ""
    claude_working_dir: str = "/tmp/claude-tasks"

    # Security: Allowed base directories for projects
    # Comma-separated list of directories where projects can be registered
    # Projects must be within one of these directories (or subdirectories)
    # Empty string = no restrictions (for local development)
    # Example: "/home,/projects,/var/www"
    allowed_project_dirs: str = ""

    # Logging
    log_level: str = "info"

    # Phase 2+ (optional)
    nats_url: str | None = None
    redis_url: str | None = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def is_orchestrator(self) -> bool:
        """Check if running as central orchestrator."""
        return self.service_mode == "orchestrator"

    def get_allowed_project_dirs(self) -> list[Path]:
        """Get list of allowed project base directories."""
        if not self.allowed_project_dirs.strip():
            return []
        return [
            Path(d.strip()).resolve()
            for d in self.allowed_project_dirs.split(",")
            if d.strip()
        ]

    def is_path_allowed(self, path: Path) -> bool:
        """Check if a path is within an allowed directory.

        Args:
            path: Path to check (will be resolved)

        Returns:
            True if path is allowed (or no restrictions configured)
        """
        allowed_dirs = self.get_allowed_project_dirs()

        # No restrictions configured = allow all (for local development)
        if not allowed_dirs:
            return True

        resolved_path = path.resolve()

        # Check if path is within any allowed directory
        for allowed_dir in allowed_dirs:
            try:
                resolved_path.relative_to(allowed_dir)
                return True
            except ValueError:
                continue

        return False


settings = Settings()
