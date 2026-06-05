"""Central configuration and LLM initialisation for Aegis-X Enterprise.

This module is responsible for two things:

1.  Loading the runtime configuration from the environment / ``.env`` file via
    Pydantic-Settings v2 (:class:`Settings`).
2.  Providing a uniform, asynchronous LLM client abstraction
    (:class:`LLMClient`) that dispatches to the configured provider
    (OpenAI, Anthropic, Google Gemini or a local Ollama instance).

All provider SDKs are imported *lazily* so the application boots and runs even
when only one of the SDKs is installed.  When no usable credentials are present
the client transparently falls back to a deterministic *offline* mode so the
whole agent loop can still be exercised end-to-end (useful for CI and demos).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("aegis.config")


class LLMProvider(str, Enum):
    """Supported large-language-model providers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OLLAMA = "ollama"


#: Sensible default model per provider, used when ``model_name`` is unset.
DEFAULT_MODELS: dict[LLMProvider, str] = {
    LLMProvider.OPENAI: "gpt-4o",
    LLMProvider.ANTHROPIC: "claude-3-5-sonnet-latest",
    LLMProvider.GEMINI: "gemini-1.5-pro",
    LLMProvider.OLLAMA: "llama3",
}


class Settings(BaseSettings):
    """Strongly-typed runtime configuration loaded from ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- LLM selection -----------------------------------------------------
    llm_provider: LLMProvider = Field(default=LLMProvider.OPENAI)
    model_name: Optional[str] = Field(default=None)

    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    google_api_key: Optional[str] = None

    ollama_base_url: str = "http://localhost:11434"

    # -- Sandbox / execution ----------------------------------------------
    workspace_path: Path = Field(default=Path("./workspace"))
    command_timeout: int = Field(default=45, ge=1, le=3600)

    # -- Agent loop guards -------------------------------------------------
    max_iterations: int = Field(default=50, ge=1, le=1000)
    max_healing_attempts: int = Field(default=3, ge=1, le=20)

    # -- Web server --------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)

    # -- Misc --------------------------------------------------------------
    log_level: str = "INFO"

    @field_validator("workspace_path", mode="after")
    @classmethod
    def _make_absolute(cls, value: Path) -> Path:
        """Resolve the workspace to an absolute path so sandboxing is reliable."""
        return value.expanduser().resolve()

    @property
    def resolved_model(self) -> str:
        """Return the effective model name for the active provider."""
        return self.model_name or DEFAULT_MODELS[self.llm_provider]

    @property
    def active_api_key(self) -> Optional[str]:
        """Return the API key relevant for the configured provider."""
        return {
            LLMProvider.OPENAI: self.openai_api_key,
            LLMProvider.ANTHROPIC: self.anthropic_api_key,
            LLMProvider.GEMINI: self.google_api_key,
            LLMProvider.OLLAMA: "local",  # Ollama needs no key.
        }[self.llm_provider]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""
    return Settings()


class LLMClient:
    """Asynchronous, provider-agnostic LLM client.

    The public surface is intentionally tiny - :meth:`complete` takes a system
    prompt and a user prompt and returns the model's text response.  Provider
    SDKs are imported lazily inside the dispatch helpers so a missing optional
    dependency never breaks application start-up.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.provider = settings.llm_provider
        self.model = settings.resolved_model
        self.offline = not self._has_usable_credentials()
        if self.offline:
            logger.warning(
                "No usable credentials/SDK for provider '%s' - falling back to "
                "deterministic OFFLINE mode.",
                self.provider.value,
            )

    # ------------------------------------------------------------------ #
    # Credential / capability detection
    # ------------------------------------------------------------------ #
    def _has_usable_credentials(self) -> bool:
        if self.provider is LLMProvider.OLLAMA:
            return True  # Ollama is local; assume reachable, fall back on error.
        return bool(self.settings.active_api_key)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    async def complete(self, system: str, prompt: str) -> str:
        """Return the model completion for ``prompt`` given ``system`` context."""
        if self.offline:
            return self._offline_response(system, prompt)
        try:
            if self.provider is LLMProvider.OPENAI:
                return await self._complete_openai(system, prompt)
            if self.provider is LLMProvider.ANTHROPIC:
                return await self._complete_anthropic(system, prompt)
            if self.provider is LLMProvider.GEMINI:
                return await self._complete_gemini(system, prompt)
            if self.provider is LLMProvider.OLLAMA:
                return await self._complete_ollama(system, prompt)
        except Exception as exc:  # noqa: BLE001 - degrade gracefully, never crash loop
            logger.error("LLM call failed (%s); using offline fallback: %s", self.provider.value, exc)
            return self._offline_response(system, prompt)
        raise RuntimeError(f"Unsupported provider: {self.provider}")

    # ------------------------------------------------------------------ #
    # Provider implementations (lazy imports)
    # ------------------------------------------------------------------ #
    async def _complete_openai(self, system: str, prompt: str) -> str:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.settings.openai_api_key)
        resp = await client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        return resp.choices[0].message.content or ""

    async def _complete_anthropic(self, system: str, prompt: str) -> str:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=self.settings.anthropic_api_key)
        resp = await client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = [block.text for block in resp.content if getattr(block, "type", None) == "text"]
        return "".join(parts)

    async def _complete_gemini(self, system: str, prompt: str) -> str:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.settings.google_api_key)
        resp = await client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=system),
        )
        return resp.text or ""

    async def _complete_ollama(self, system: str, prompt: str) -> str:
        import httpx

        url = f"{self.settings.ollama_base_url.rstrip('/')}/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=120) as http:
            resp = await http.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        return data.get("message", {}).get("content", "")

    # ------------------------------------------------------------------ #
    # Offline / deterministic fallback
    # ------------------------------------------------------------------ #
    def _offline_response(self, system: str, prompt: str) -> str:
        """Produce a deterministic, schema-valid response without any network.

        The fallback recognises the two structured prompt shapes used by the
        agent (planning and ReAct action selection) plus the healer's
        reflection prompt, and returns valid JSON for each.  This keeps the
        full state machine demonstrable in environments without credentials.
        """
        lowered = prompt.lower()

        if "decompose" in lowered or "task_tree" in lowered or "break the goal" in lowered:
            goal = self._extract_goal(prompt)
            tasks = [
                {"title": f"Analyse requirements for: {goal}"},
                {"title": f"Implement a solution for: {goal}"},
                {"title": "Verify the result and report"},
            ]
            return json.dumps({"tasks": tasks})

        if "next action" in lowered or '"tool"' in lowered or "available tools" in lowered:
            # In offline mode we cannot reason about tools, so finish the task.
            return json.dumps(
                {
                    "thought": "Offline mode: no LLM available, completing task deterministically.",
                    "final": True,
                    "summary": "Task acknowledged in offline mode.",
                }
            )

        if "corrected code" in lowered or "reflexions" in lowered or "you have produced" in lowered:
            return json.dumps(
                {
                    "explanation": "Offline mode cannot synthesise a real fix.",
                    "code": "",
                    "filename": "",
                }
            )

        return "Offline mode: no language model is configured."

    @staticmethod
    def _extract_goal(prompt: str) -> str:
        match = re.search(r"GOAL:\s*(.+)", prompt)
        if match:
            return match.group(1).strip().splitlines()[0][:200]
        return prompt.strip().splitlines()[0][:200] if prompt.strip() else "the task"


def build_llm_client(settings: Optional[Settings] = None) -> LLMClient:
    """Factory that initialises the LLM client from settings."""
    return LLMClient(settings or get_settings())


def extract_json(text: str) -> Optional[dict]:
    """Best-effort extraction of a single JSON object from ``text``.

    Handles raw JSON, ```json fenced blocks and JSON embedded in surrounding
    prose by locating the outermost balanced ``{...}`` region.
    """
    if not text:
        return None
    stripped = text.strip()
    # Strip a leading markdown code fence if present.
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    if fence:
        stripped = fence.group(1).strip()
    try:
        loaded = json.loads(stripped)
        return loaded if isinstance(loaded, dict) else None
    except json.JSONDecodeError:
        pass
    # Fall back to locating the first balanced brace span.
    start = stripped.find("{")
    if start == -1:
        return None
    depth = 0
    for idx in range(start, len(stripped)):
        char = stripped[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    loaded = json.loads(stripped[start : idx + 1])
                    return loaded if isinstance(loaded, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    logging.basicConfig(level=logging.INFO)
    s = get_settings()
    print(f"Provider : {s.llm_provider.value}")
    print(f"Model    : {s.resolved_model}")
    print(f"Workspace: {s.workspace_path}")
    client = build_llm_client(s)
    print(asyncio.run(client.complete("You are a test.", "Say hello.")))
