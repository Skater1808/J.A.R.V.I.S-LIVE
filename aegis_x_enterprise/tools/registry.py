"""Tool registry and the built-in tool implementations.

The :class:`ToolRegistry` is the single point through which the agent core and
all plugins access executable capabilities.  The built-in tools cover the three
fundamental capability classes required by an autonomous coding agent:

* **File-system** - ``write_file``, ``read_file``, ``list_dir``
* **HTTP** - ``http_request``
* **Terminal** - ``run_command`` (sandboxed, timeout-guarded)
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from execution.local_env import LocalEnvironment
from tools.base import BaseTool, ToolResult

logger = logging.getLogger("aegis.tools")


class ToolRegistry:
    """A registry that stores and dispatches :class:`BaseTool` instances."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            logger.warning("Tool '%s' already registered - overwriting.", tool.name)
        self._tools[tool.name] = tool
        logger.info("Registered tool: %s", tool.name)

    def register_all(self, tools: Iterable[BaseTool]) -> None:
        for tool in tools:
            self.register(tool)

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> list[dict[str, Any]]:
        return [tool.spec() for tool in self._tools.values()]

    async def execute(self, name: str, **kwargs: Any) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult(
                success=False,
                error=f"Unknown tool '{name}'. Available: {', '.join(self.names()) or 'none'}",
                exit_code=1,
            )
        try:
            return await tool.execute(**kwargs)
        except PermissionError as exc:
            logger.error("Sandbox violation in tool '%s': %s", name, exc)
            return ToolResult(success=False, error=f"PermissionError: {exc}", exit_code=126)
        except TypeError as exc:
            return ToolResult(success=False, error=f"Bad arguments for '{name}': {exc}", exit_code=2)
        except Exception as exc:  # noqa: BLE001 - tools must never crash the loop
            logger.exception("Tool '%s' raised an unexpected error", name)
            return ToolResult(success=False, error=f"{type(exc).__name__}: {exc}", exit_code=1)


# --------------------------------------------------------------------------- #
# Built-in tools
# --------------------------------------------------------------------------- #
class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Create or overwrite a file inside the sandboxed workspace."
    parameters = {"path": "Relative path inside the workspace.", "content": "Full file content."}

    def __init__(self, env: LocalEnvironment) -> None:
        super().__init__()
        self._env = env

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = str(kwargs["path"])
        content = str(kwargs.get("content", ""))
        written = await self._env.write_file(path, content)
        return ToolResult(success=True, output=f"Wrote {len(content)} bytes to {written}")


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read the contents of a file inside the sandboxed workspace."
    parameters = {"path": "Relative path inside the workspace."}

    def __init__(self, env: LocalEnvironment) -> None:
        super().__init__()
        self._env = env

    async def execute(self, **kwargs: Any) -> ToolResult:
        content = await self._env.read_file(str(kwargs["path"]))
        return ToolResult(success=True, output=content)


class ListDirTool(BaseTool):
    name = "list_dir"
    description = "List the entries of a directory inside the sandboxed workspace."
    parameters = {"path": "Relative directory path (defaults to workspace root)."}

    def __init__(self, env: LocalEnvironment) -> None:
        super().__init__()
        self._env = env

    async def execute(self, **kwargs: Any) -> ToolResult:
        entries = await self._env.list_dir(str(kwargs.get("path", ".")))
        return ToolResult(success=True, output="\n".join(entries), metadata={"entries": entries})


class RunCommandTool(BaseTool):
    name = "run_command"
    description = "Run a shell command inside the workspace with a hard timeout."
    parameters = {"command": "The shell command to execute.", "timeout": "Optional timeout (s)."}

    def __init__(self, env: LocalEnvironment) -> None:
        super().__init__()
        self._env = env

    async def execute(self, **kwargs: Any) -> ToolResult:
        command = str(kwargs["command"])
        timeout = kwargs.get("timeout")
        result = await self._env.run_command(command, timeout=int(timeout) if timeout else None)
        return ToolResult(
            success=result.success,
            output=result.stdout,
            error=result.stderr,
            exit_code=result.exit_code,
            metadata={"timed_out": result.timed_out, "command": command},
        )


class HttpRequestTool(BaseTool):
    name = "http_request"
    description = "Perform an outbound HTTP request and return the response body."
    parameters = {
        "url": "The target URL.",
        "method": "HTTP method (GET, POST, ...). Defaults to GET.",
        "headers": "Optional dict of request headers.",
        "json": "Optional JSON body for POST/PUT requests.",
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        import httpx

        url = str(kwargs["url"])
        method = str(kwargs.get("method", "GET")).upper()
        headers = kwargs.get("headers") or None
        json_body = kwargs.get("json")
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.request(method, url, headers=headers, json=json_body)
        return ToolResult(
            success=resp.is_success,
            output=resp.text[:20000],
            exit_code=0 if resp.is_success else 1,
            metadata={"status_code": resp.status_code, "url": str(resp.url)},
        )


def build_default_registry(env: LocalEnvironment) -> ToolRegistry:
    """Construct a registry pre-populated with the built-in tools."""
    registry = ToolRegistry()
    registry.register_all(
        [
            WriteFileTool(env),
            ReadFileTool(env),
            ListDirTool(env),
            RunCommandTool(env),
            HttpRequestTool(),
        ]
    )
    return registry
