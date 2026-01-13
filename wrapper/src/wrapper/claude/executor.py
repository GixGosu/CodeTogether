"""Claude Code CLI executor."""

import asyncio
import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from wrapper.api.models import ApprovalRequest, TaskStatus

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of a Claude Code execution."""

    status: TaskStatus
    output: str
    error: str | None = None
    approval_request: ApprovalRequest | None = None
    session_id: str | None = None


@dataclass
class ClaudeExecutor:
    """Executes Claude Code CLI commands."""

    working_dir: Path
    env: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Ensure working directory exists."""
        self.working_dir.mkdir(parents=True, exist_ok=True)

    async def execute(
        self,
        prompt: str,
        session_id: str | None = None,
        timeout: float = 300.0,
    ) -> ExecutionResult:
        """
        Execute a Claude Code command.

        Args:
            prompt: The prompt/task to send to Claude
            session_id: Optional session ID to continue a previous session
            timeout: Maximum execution time in seconds

        Returns:
            ExecutionResult with status, output, and any errors
        """
        # Build command arguments
        # Permissions are configured via .claude/settings.json
        cmd = ["claude", "-p", prompt, "--output-format", "json"]

        # Add session continuation if provided
        if session_id:
            cmd.extend(["--resume", session_id])

        # Merge environment
        env = os.environ.copy()
        env.update(self.env)

        logger.info(f"Executing Claude Code: {' '.join(cmd[:4])}...")

        def run_subprocess() -> subprocess.CompletedProcess[bytes]:
            """Run subprocess in a thread (Windows compatible)."""
            return subprocess.run(
                cmd,
                capture_output=True,
                cwd=self.working_dir,
                env=env,
                timeout=timeout,
            )

        try:
            # Run in thread pool to avoid Windows asyncio subprocess issues
            try:
                result = await asyncio.to_thread(run_subprocess)
            except subprocess.TimeoutExpired:
                return ExecutionResult(
                    status=TaskStatus.FAILED,
                    output="",
                    error=f"Execution timed out after {timeout} seconds",
                )

            stdout_str = result.stdout.decode("utf-8", errors="replace")
            stderr_str = result.stderr.decode("utf-8", errors="replace")

            if result.returncode != 0:
                logger.error(f"Claude Code failed with code {result.returncode}: {stderr_str}")
                return ExecutionResult(
                    status=TaskStatus.FAILED,
                    output=stdout_str,
                    error=stderr_str or f"Process exited with code {result.returncode}",
                )

            # Parse JSON output
            return self._parse_output(stdout_str, stderr_str)

        except FileNotFoundError:
            logger.error("Claude Code CLI not found. Is it installed?")
            return ExecutionResult(
                status=TaskStatus.FAILED,
                output="",
                error="Claude Code CLI not found. Please install it with: npm install -g @anthropic-ai/claude-code",
            )
        except Exception as e:
            logger.exception("Unexpected error executing Claude Code")
            return ExecutionResult(
                status=TaskStatus.FAILED,
                output="",
                error=str(e),
            )

    def _parse_output(self, stdout: str, stderr: str) -> ExecutionResult:
        """Parse Claude Code JSON output."""
        try:
            # Claude Code outputs JSON with session info
            data = json.loads(stdout)

            # Extract relevant fields
            output = data.get("result", data.get("output", stdout))
            session_id = data.get("session_id")

            # Check for approval requests
            approval_request = None
            if data.get("needs_approval"):
                approval_data = data.get("approval_request", {})
                approval_request = ApprovalRequest(
                    action=approval_data.get("action", "unknown"),
                    description=approval_data.get("description", "Action requires approval"),
                    options=approval_data.get("options", []),
                )
                return ExecutionResult(
                    status=TaskStatus.NEEDS_APPROVAL,
                    output=output,
                    approval_request=approval_request,
                    session_id=session_id,
                )

            return ExecutionResult(
                status=TaskStatus.COMPLETED,
                output=output if isinstance(output, str) else json.dumps(output),
                session_id=session_id,
            )

        except json.JSONDecodeError:
            # If not JSON, treat as plain text output
            logger.debug("Output is not JSON, treating as plain text")
            return ExecutionResult(
                status=TaskStatus.COMPLETED,
                output=stdout,
            )

    async def submit_approval(
        self,
        session_id: str,
        option_id: str,
        custom_response: str | None = None,
    ) -> ExecutionResult:
        """
        Submit an approval response and continue execution.

        Args:
            session_id: The session to continue
            option_id: The selected option ID
            custom_response: Optional custom response text

        Returns:
            ExecutionResult with the continuation result
        """
        # Build the approval response prompt
        response = custom_response if custom_response else option_id

        # Continue the session with the approval
        return await self.execute(
            prompt=response,
            session_id=session_id,
        )
