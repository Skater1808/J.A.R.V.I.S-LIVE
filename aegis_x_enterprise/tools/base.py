"""Abstract base classes for tools and plugins.

A *tool* is a single capability the agent can invoke (write a file, run a
command, perform an HTTP request, ...).  A *plugin* is a packaged collection of
tools that is discovered and loaded dynamically at runtime by the
:class:`~plugins.manager.PluginManager`.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids import cycle
    from tools.registry import ToolRegistry


@dataclass
class ToolResult:
    """Standardised result returned by every tool invocation."""

    success: bool
    output: str = ""
    error: str = ""
    exit_code: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "exit_code": self.exit_code,
            "metadata": self.metadata,
        }


class BaseTool(abc.ABC):
    """Abstract base class for an individual agent tool."""

    #: Unique, machine-friendly identifier used by the LLM to select the tool.
    name: str = ""
    #: Human-readable description surfaced to the LLM in the action prompt.
    description: str = ""
    #: JSON-schema-like mapping of ``arg_name -> description`` for the LLM.
    parameters: dict[str, str] = {}

    def __init__(self) -> None:
        if not self.name:
            raise ValueError(f"{type(self).__name__} must define a non-empty 'name'.")

    @abc.abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Run the tool with the supplied keyword arguments."""
        raise NotImplementedError

    def spec(self) -> dict[str, Any]:
        """Return a serialisable description used when prompting the LLM."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class BasePlugin(abc.ABC):
    """Abstract base class every plugin must inherit from."""

    #: Display name of the plugin.
    name: str = ""
    #: Short description of what the plugin provides.
    description: str = ""
    #: Semantic version of the plugin.
    version: str = "0.1.0"

    @abc.abstractmethod
    def register_tools(self, registry: "ToolRegistry") -> None:
        """Register all tools provided by this plugin with ``registry``."""
        raise NotImplementedError
