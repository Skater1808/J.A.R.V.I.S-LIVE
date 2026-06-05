"""FastAPI application: REST control surface + WebSocket telemetry.

The app wires together the whole agent stack (sandbox, tool registry, plugin
manager, LLM client, healer, memory and the :class:`~agent.core.AgentCore`) and
exposes:

* ``GET  /``          - the single-page Tailwind dashboard.
* ``POST /start``     - start a new autonomous run for a goal.
* ``POST /pause``     - toggle pause / resume of the running agent.
* ``POST /stop``      - emergency kill-switch.
* ``GET  /state``     - the current structured agent state.
* ``WS   /ws/logs``   - real-time event stream (status, log, task_update, error).

Every WebSocket frame follows the schema::

    {"type": "status|log|task_update|error", "payload": {...}, "timestamp": "ISO-8601"}
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from config import Settings, build_llm_client, get_settings
from agent.core import AgentCore, STATE_FILE
from agent.healer import HealerModule
from agent.memory import Memory
from execution.local_env import LocalEnvironment
from plugins.manager import PluginManager
from tools.registry import build_default_registry

logger = logging.getLogger("aegis.ui")

_BASE_DIR = Path(__file__).resolve().parent
_TEMPLATES = Jinja2Templates(directory=str(_BASE_DIR / "templates"))


class ConnectionManager:
    """Tracks active WebSocket clients and broadcasts standardised events."""

    def __init__(self, history_size: int = 200) -> None:
        self.active: set[WebSocket] = set()
        self.history: deque[dict[str, Any]] = deque(maxlen=history_size)
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self.active.add(websocket)
        # Replay recent history so a freshly-connected client is in sync.
        for event in list(self.history):
            await websocket.send_json(event)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self.active.discard(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Stamp, store and fan out an event to all connected clients."""
        event = {
            "type": message.get("type", "log"),
            "payload": message.get("payload", {}),
            "timestamp": message.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        }
        self.history.append(event)
        stale: list[WebSocket] = []
        for ws in list(self.active):
            try:
                await ws.send_json(event)
            except Exception:  # noqa: BLE001 - drop dead connections
                stale.append(ws)
        for ws in stale:
            await self.disconnect(ws)


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    """Application factory that assembles and wires the entire agent stack."""
    settings = settings or get_settings()
    manager = ConnectionManager()

    env = LocalEnvironment(settings.workspace_path, command_timeout=settings.command_timeout)
    registry = build_default_registry(env)
    llm = build_llm_client(settings)
    memory = Memory(
        db_path=settings.workspace_path.parent / "aegis_memory.db",
        state_path=STATE_FILE,
    )

    async def emit(message: dict[str, Any]) -> None:
        await manager.broadcast(message)

    healer = HealerModule(llm, env, max_attempts=settings.max_healing_attempts, emit=emit)
    core = AgentCore(settings, llm, registry, env, healer, memory, emit=emit)
    plugin_manager = PluginManager(_BASE_DIR.parent / "plugins", registry)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await memory.initialize()
        await plugin_manager.discover_and_load()
        logger.info(
            "Aegis-X ready. Provider=%s model=%s tools=%s",
            settings.llm_provider.value, settings.resolved_model, registry.names(),
        )
        yield
        core.stop()

    app = FastAPI(title="Aegis-X Enterprise", version="1.0.0", lifespan=lifespan)
    app.state.core = core
    app.state.manager = manager
    app.state.settings = settings
    app.state.run_task = None

    # ------------------------------------------------------------------ #
    # Routes
    # ------------------------------------------------------------------ #
    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {
                "provider": settings.llm_provider.value,
                "model": settings.resolved_model,
                "max_iterations": settings.max_iterations,
            },
        )

    @app.post("/start")
    async def start(payload: dict[str, Any]) -> JSONResponse:
        goal = str(payload.get("goal", "")).strip()
        if not goal:
            return JSONResponse({"ok": False, "error": "Missing 'goal'."}, status_code=400)
        if core.is_running:
            # Treat a start while running as a resume if the agent is paused.
            core.resume()
            return JSONResponse({"ok": True, "status": "resumed", "state": core.state.value})
        app.state.run_task = asyncio.create_task(core.run(goal))
        return JSONResponse({"ok": True, "status": "started", "goal": goal})

    @app.post("/pause")
    async def pause() -> JSONResponse:
        # Toggle: pause if running unpaused, otherwise resume.
        if core._resume_event.is_set():  # noqa: SLF001 - intentional internal toggle
            core.pause()
            return JSONResponse({"ok": True, "status": "paused", "state": core.state.value})
        core.resume()
        return JSONResponse({"ok": True, "status": "resumed", "state": core.state.value})

    @app.post("/stop")
    async def stop() -> JSONResponse:
        core.stop()
        return JSONResponse({"ok": True, "status": "stopping", "state": core.state.value})

    @app.get("/state")
    async def state() -> JSONResponse:
        return JSONResponse(core.snapshot())

    @app.websocket("/ws/logs")
    async def ws_logs(websocket: WebSocket) -> None:
        await manager.connect(websocket)
        # Push the current state immediately on connect.
        await websocket.send_json(
            {
                "type": "status",
                "payload": {"state": core.state.value, "iteration": core.iteration_count},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        try:
            while True:
                # We don't require inbound messages, but keep the socket alive.
                await websocket.receive_text()
        except WebSocketDisconnect:
            await manager.disconnect(websocket)
        except Exception:  # noqa: BLE001
            await manager.disconnect(websocket)

    return app
