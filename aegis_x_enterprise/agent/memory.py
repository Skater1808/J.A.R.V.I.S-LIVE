"""Context history and state persistence.

:class:`Memory` keeps an in-memory conversation/context buffer and durably
persists two things:

* a rolling event/message log in a SQLite database (via :mod:`aiosqlite`), and
* the structured agent state document (``agent_state.json``) as a JSON file in
  the agent's own directory.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("aegis.memory")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT    NOT NULL,
    role      TEXT    NOT NULL,
    content   TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS state_snapshots (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT    NOT NULL,
    snapshot  TEXT    NOT NULL
);
"""


@dataclass
class Message:
    role: str
    content: str
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content, "ts": self.ts}


class Memory:
    """Async context history with SQLite + JSON persistence."""

    def __init__(self, db_path: Path, state_path: Path, max_context: int = 40) -> None:
        self.db_path = db_path
        self.state_path = state_path
        self.max_context = max_context
        self._history: list[Message] = []

    async def initialize(self) -> None:
        """Create the database schema if needed."""
        import aiosqlite

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()
        logger.info("Memory initialised (db=%s, state=%s)", self.db_path, self.state_path)

    # ------------------------------------------------------------------ #
    # Conversation / context history
    # ------------------------------------------------------------------ #
    async def add_message(self, role: str, content: str) -> None:
        import aiosqlite

        msg = Message(role=role, content=content)
        self._history.append(msg)
        # Bound the in-memory context window.
        if len(self._history) > self.max_context:
            self._history = self._history[-self.max_context :]
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO messages (ts, role, content) VALUES (?, ?, ?)",
                (msg.ts, msg.role, msg.content),
            )
            await db.commit()

    def context(self) -> list[dict[str, str]]:
        """Return the current bounded context window as dicts."""
        return [m.to_dict() for m in self._history]

    def context_text(self) -> str:
        """Return the context window rendered as a compact transcript."""
        return "\n".join(f"[{m.role}] {m.content}" for m in self._history)

    # ------------------------------------------------------------------ #
    # State persistence
    # ------------------------------------------------------------------ #
    async def persist_state(self, state: dict[str, Any]) -> None:
        """Write the agent state document to disk and snapshot it in SQLite."""
        import aiosqlite

        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        serialised = json.dumps(state, indent=2, ensure_ascii=False)
        self.state_path.write_text(serialised, encoding="utf-8")

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO state_snapshots (ts, snapshot) VALUES (?, ?)",
                (datetime.now(timezone.utc).isoformat(), serialised),
            )
            await db.commit()

    def load_state(self) -> dict[str, Any] | None:
        """Load the last persisted state document, if any."""
        if not self.state_path.is_file():
            return None
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load state document: %s", exc)
            return None
