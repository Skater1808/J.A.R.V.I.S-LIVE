"""Secure local execution environment.

Every file-system and terminal operation performed by the agent funnels through
:class:`LocalEnvironment`.  Two hard guarantees are enforced:

* **Workspace locking** - all paths are confined to the configured
  ``workspace`` directory.  :func:`validate_path` resolves the candidate path
  and raises :class:`PermissionError` if it escapes the sandbox.
* **Execution timeouts** - every subprocess is launched asynchronously and
  killed if it exceeds a hard timeout (default 45s), preventing hung or
  runaway processes from blocking the agent.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("aegis.execution")


@dataclass
class CommandResult:
    """Outcome of a sandboxed shell command."""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def validate_path(target_path: str | os.PathLike[str], workspace_root: Path) -> Path:
    """Resolve ``target_path`` and ensure it stays inside ``workspace_root``.

    Args:
        target_path: A path relative to (or inside) the workspace.
        workspace_root: The absolute, resolved sandbox root.

    Returns:
        The resolved absolute :class:`~pathlib.Path` inside the workspace.

    Raises:
        PermissionError: If the resolved path escapes the workspace boundary.
    """
    root = workspace_root.resolve()
    candidate = Path(target_path)
    # Interpret relative paths as relative to the workspace root.
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()

    # ``is_relative_to`` (3.9+) gives a robust containment check that is immune
    # to ``..`` traversal because both sides are fully resolved first.
    if resolved != root and not resolved.is_relative_to(root):
        raise PermissionError(
            f"Path traversal blocked: '{resolved}' is outside the workspace '{root}'."
        )
    return resolved


class LocalEnvironment:
    """Sandboxed file-system + subprocess runner bound to a workspace."""

    def __init__(self, workspace_root: Path, command_timeout: int = 45) -> None:
        self.workspace_root = workspace_root.resolve()
        self.command_timeout = command_timeout
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        logger.info("Sandbox initialised at %s (timeout=%ss)", self.workspace_root, command_timeout)

    # ------------------------------------------------------------------ #
    # Path helpers
    # ------------------------------------------------------------------ #
    def resolve(self, target_path: str) -> Path:
        """Validate and resolve ``target_path`` within the sandbox."""
        return validate_path(target_path, self.workspace_root)

    # ------------------------------------------------------------------ #
    # File operations
    # ------------------------------------------------------------------ #
    async def write_file(self, target_path: str, content: str) -> Path:
        path = self.resolve(target_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_text, content, "utf-8")
        logger.info("Wrote %d bytes to %s", len(content), path)
        return path

    async def read_file(self, target_path: str) -> str:
        path = self.resolve(target_path)
        if not path.is_file():
            raise FileNotFoundError(f"No such file in workspace: {target_path}")
        return await asyncio.to_thread(path.read_text, "utf-8")

    async def list_dir(self, target_path: str = ".") -> list[str]:
        path = self.resolve(target_path)
        if not path.exists():
            return []
        return sorted(
            f"{p.name}/" if p.is_dir() else p.name
            for p in await asyncio.to_thread(lambda: list(path.iterdir()))
        )

    async def delete(self, target_path: str) -> None:
        path = self.resolve(target_path)
        if path.is_dir():
            await asyncio.to_thread(lambda: [c.unlink() for c in path.glob("*") if c.is_file()])
            await asyncio.to_thread(path.rmdir)
        elif path.exists():
            await asyncio.to_thread(path.unlink)

    # ------------------------------------------------------------------ #
    # Subprocess execution
    # ------------------------------------------------------------------ #
    async def run_command(self, command: str, timeout: int | None = None) -> CommandResult:
        """Run ``command`` inside the workspace with a hard timeout.

        The command's working directory is locked to the workspace root and the
        process is force-killed if it overruns the timeout budget.
        """
        effective_timeout = timeout if timeout is not None else self.command_timeout
        logger.info("Executing (timeout=%ss): %s", effective_timeout, command)

        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(self.workspace_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=effective_timeout)
        except asyncio.TimeoutError:
            await self._terminate(proc)
            logger.warning("Command timed out after %ss: %s", effective_timeout, command)
            return CommandResult(
                command=command,
                exit_code=124,  # conventional timeout exit code
                stdout="",
                stderr=f"Command timed out after {effective_timeout}s and was terminated.",
                timed_out=True,
            )

        result = CommandResult(
            command=command,
            exit_code=proc.returncode if proc.returncode is not None else -1,
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
        )
        logger.info("Command exited with code %s", result.exit_code)
        return result

    @staticmethod
    async def _terminate(proc: asyncio.subprocess.Process) -> None:
        """Best-effort termination of a runaway process."""
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=5)
        except (asyncio.TimeoutError, ProcessLookupError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass
