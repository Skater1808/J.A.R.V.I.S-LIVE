"""Hermes-style iterative self-healing engine.

When a sandboxed command or unit test exits with a non-zero status the agent
core pauses execution and hands control to :class:`HealerModule`.  The healer
sends a focused *reflection prompt* to the LLM, applies the returned corrected
code directly to the workspace and lets the core retry.  After
``max_attempts`` consecutive failures at the *same location* the healer
escalates, signalling the core to transition to the ``FAILED`` state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from config import LLMClient, extract_json
from execution.local_env import LocalEnvironment

logger = logging.getLogger("aegis.healer")

EmitFn = Callable[[dict], Awaitable[None]]

_REFLECTION_SYSTEM = (
    "You are Hermes, an elite software-repair specialist. You receive failing "
    "code together with the command that was run and its full stderr. You "
    "diagnose the root cause (syntax error, missing library, or logic error) "
    "and return a corrected, complete replacement for the file. "
    'Respond with STRICT JSON only: {"explanation": "<exactly one sentence>", '
    '"filename": "<relative path to overwrite>", "code": "<the full corrected file content>"}.'
)

_REFLECTION_TEMPLATE = """You have produced the following error.

COMMAND:
{command}

STDERR:
{stderr}

CURRENT FILE ({filename}):
```
{code}
```

Analyse the cause (syntax, missing library, or logic error). Generate a corrected
code block (the COMPLETE file content) and explain the correction in exactly one
sentence. Return the required STRICT JSON object."""


@dataclass
class HealResult:
    """Outcome of a single healing attempt."""

    healed: bool
    escalated: bool
    attempts: int
    explanation: str = ""
    filename: str = ""
    new_code: str = ""


class HealerModule:
    """Iterative, LLM-driven code repair with per-location attempt limits."""

    def __init__(
        self,
        llm: LLMClient,
        env: LocalEnvironment,
        max_attempts: int = 3,
        emit: Optional[EmitFn] = None,
    ) -> None:
        self.llm = llm
        self.env = env
        self.max_attempts = max_attempts
        self._emit = emit
        self._attempts: dict[str, int] = {}

    def attempts_for(self, location: str) -> int:
        return self._attempts.get(location, 0)

    def reset(self, location: str) -> None:
        """Clear the attempt counter for a location once it succeeds."""
        self._attempts.pop(location, None)

    async def heal_code(
        self,
        *,
        filename: str,
        code: str,
        command: str,
        stderr: str,
        location: Optional[str] = None,
    ) -> HealResult:
        """Attempt to repair ``code`` that failed running ``command``.

        Args:
            filename: Relative workspace path of the file to patch.
            code: The current (failing) file content.
            command: The command that produced the failure.
            stderr: The captured standard-error output.
            location: Stable identifier for the failure site (defaults to the
                command + filename) used to enforce the attempt limit.
        """
        key = location or f"{filename}::{command}"
        self._attempts[key] = self._attempts.get(key, 0) + 1
        attempt = self._attempts[key]

        await self._notify(
            "log",
            {"source": "healer", "message": f"Healing attempt {attempt}/{self.max_attempts} for '{filename}'."},
        )

        if attempt > self.max_attempts:
            logger.error("Healing escalated for %s after %d attempts.", key, attempt - 1)
            await self._notify(
                "error",
                {"source": "healer", "message": f"Escalating: '{filename}' still failing after {self.max_attempts} attempts."},
            )
            return HealResult(healed=False, escalated=True, attempts=attempt - 1, filename=filename)

        prompt = _REFLECTION_TEMPLATE.format(
            command=command, stderr=stderr[:6000], filename=filename, code=code[:12000]
        )
        raw = await self.llm.complete(_REFLECTION_SYSTEM, prompt)
        parsed = extract_json(raw)

        if not parsed or not parsed.get("code"):
            logger.warning("Healer received an unusable LLM response for %s.", key)
            await self._notify(
                "log",
                {"source": "healer", "message": "LLM did not return a usable correction."},
            )
            escalated = attempt >= self.max_attempts
            return HealResult(
                healed=False,
                escalated=escalated,
                attempts=attempt,
                filename=filename,
                explanation=(parsed or {}).get("explanation", ""),
            )

        target = str(parsed.get("filename") or filename)
        new_code = str(parsed["code"])
        explanation = str(parsed.get("explanation", "")).strip()

        await self.env.write_file(target, new_code)
        logger.info("Applied healing patch to %s: %s", target, explanation)
        await self._notify(
            "log",
            {"source": "healer", "message": f"Applied fix to '{target}': {explanation}"},
        )

        return HealResult(
            healed=True,
            escalated=False,
            attempts=attempt,
            explanation=explanation,
            filename=target,
            new_code=new_code,
        )

    async def _notify(self, event_type: str, payload: dict) -> None:
        if self._emit is not None:
            await self._emit({"type": event_type, "payload": payload})
