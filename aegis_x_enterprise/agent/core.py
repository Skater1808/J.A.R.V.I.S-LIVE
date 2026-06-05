"""Asynchronous ReAct core loop and finite state machine.

:class:`AgentCore` drives the autonomous agent through a strict
:class:`AgentState` machine.  The execution loop follows the ReAct pattern
(Reasoning + Acting): for each task the LLM proposes a *thought* and an
*action* (a tool call), the tool is executed inside the sandbox, and the
observation is fed back into the next reasoning step.  Failing commands trigger
the Hermes-style :class:`~agent.healer.HealerModule`.

The complete internal state is mirrored to ``agent_state.json`` on every
transition so the UI and external observers always have an authoritative view.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Awaitable, Callable, Optional

from config import LLMClient, Settings, extract_json
from agent.healer import HealerModule
from agent.memory import Memory
from execution.local_env import LocalEnvironment
from tools.registry import ToolRegistry

logger = logging.getLogger("aegis.core")

EmitFn = Callable[[dict], Awaitable[None]]

STATE_FILE = Path(__file__).resolve().parent / "agent_state.json"


class AgentState(str, Enum):
    IDLE = "IDLE"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    TESTING = "TESTING"
    HEALING = "HEALING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


@dataclass
class Task:
    id: int
    title: str
    status: TaskStatus = TaskStatus.PENDING
    error_log: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status.value,
            "error_log": self.error_log,
        }


_PLANNER_SYSTEM = (
    "You are the planning module of an autonomous software engineering agent. "
    "Decompose the user's GOAL into a concise, ordered task tree of concrete, "
    "verifiable steps. Break the goal into 2-6 tasks. "
    'Respond with STRICT JSON only: {"tasks": [{"title": "..."}, ...]}.'
)

_ACTOR_SYSTEM = (
    "You are the acting module of an autonomous software engineering agent using "
    "the ReAct pattern. Given the current task and the available tools, decide the "
    "single next action. To call a tool respond with STRICT JSON: "
    '{"thought": "...", "tool": "<tool_name>", "args": {...}}. '
    "When the task is fully complete respond with STRICT JSON: "
    '{"thought": "...", "final": true, "summary": "..."}. '
    "All file paths are relative to a sandboxed workspace."
)


class AgentCore:
    """The autonomous agent's state machine and ReAct execution loop."""

    def __init__(
        self,
        settings: Settings,
        llm: LLMClient,
        registry: ToolRegistry,
        env: LocalEnvironment,
        healer: HealerModule,
        memory: Memory,
        emit: Optional[EmitFn] = None,
    ) -> None:
        self.settings = settings
        self.llm = llm
        self.registry = registry
        self.env = env
        self.healer = healer
        self.memory = memory
        self._emit = emit

        self.state: AgentState = AgentState.IDLE
        self.goal: str = ""
        self.task_tree: list[Task] = []
        self.iteration_count: int = 0

        self._last_written_file: Optional[str] = None
        self._stop_requested = False
        self._resume_event = asyncio.Event()
        self._resume_event.set()  # not paused initially
        self._run_lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Control surface (wired to the REST endpoints)
    # ------------------------------------------------------------------ #
    @property
    def is_running(self) -> bool:
        return self.state in {AgentState.PLANNING, AgentState.EXECUTING, AgentState.TESTING, AgentState.HEALING}

    def pause(self) -> None:
        self._resume_event.clear()
        logger.info("Pause requested.")

    def resume(self) -> None:
        self._resume_event.set()
        logger.info("Resume requested.")

    def stop(self) -> None:
        self._stop_requested = True
        self._resume_event.set()  # unblock any paused wait so the loop can exit
        logger.info("Stop (kill-switch) requested.")

    # ------------------------------------------------------------------ #
    # Main entry point
    # ------------------------------------------------------------------ #
    async def run(self, goal: str) -> None:
        """Execute the full autonomous loop for ``goal``."""
        if self._run_lock.locked():
            logger.warning("Agent is already running; ignoring new goal.")
            return
        async with self._run_lock:
            self.goal = goal.strip()
            self.iteration_count = 0
            self.task_tree = []
            self._stop_requested = False
            self._resume_event.set()
            await self.memory.add_message("user", self.goal)
            logger.info("New goal accepted: %s", self.goal)

            try:
                await self._set_state(AgentState.PLANNING)
                await self._plan()

                await self._set_state(AgentState.EXECUTING)
                await self._execute_tasks()

                if self.state not in {AgentState.FAILED}:
                    await self._set_state(AgentState.COMPLETED)
            except Exception:  # noqa: BLE001 - surface any crash as FAILED state
                logger.exception("Unhandled error in agent loop.")
                await self._set_state(AgentState.FAILED)

    # ------------------------------------------------------------------ #
    # PLANNING
    # ------------------------------------------------------------------ #
    async def _plan(self) -> None:
        prompt = f"GOAL: {self.goal}\n\nDecompose this goal into a task tree."
        raw = await self.llm.complete(_PLANNER_SYSTEM, prompt)
        parsed = extract_json(raw) or {}
        tasks = parsed.get("tasks") or []

        if not tasks:
            tasks = [{"title": self.goal or "Complete the requested goal"}]

        self.task_tree = [
            Task(id=i + 1, title=str(t.get("title", f"Task {i + 1}")))
            for i, t in enumerate(tasks)
        ]
        await self.memory.add_message("assistant", f"Plan: {[t.title for t in self.task_tree]}")
        await self._emit_event("task_update", {"tasks": [t.to_dict() for t in self.task_tree]})
        await self._persist()

    # ------------------------------------------------------------------ #
    # EXECUTION
    # ------------------------------------------------------------------ #
    async def _execute_tasks(self) -> None:
        for task in self.task_tree:
            if not await self._guard():
                return
            await self._set_task_status(task, TaskStatus.RUNNING)
            ok = await self._run_react_task(task)
            if ok:
                await self._set_task_status(task, TaskStatus.DONE)
            else:
                await self._set_task_status(task, TaskStatus.FAILED)
                await self._set_state(AgentState.FAILED)
                return

    async def _run_react_task(self, task: Task) -> bool:
        """Run the ReAct sub-loop for a single task. Returns success."""
        last_observation = ""
        # Per-task step budget, bounded by the global iteration hard-limit.
        for _ in range(20):
            if not await self._guard():
                return False
            self.iteration_count += 1
            if self.iteration_count > self.settings.max_iterations:
                task.error_log.append("Global iteration hard-limit reached.")
                logger.error("Iteration hard-limit (%d) reached.", self.settings.max_iterations)
                return False

            await self._set_state(AgentState.EXECUTING)
            action = await self._decide_action(task, last_observation)
            thought = str(action.get("thought", ""))
            if thought:
                await self._emit_event("log", {"source": "agent", "message": f"Thought: {thought}"})

            if action.get("final"):
                summary = str(action.get("summary", "Task complete."))
                await self.memory.add_message("assistant", f"[task {task.id}] {summary}")
                await self._emit_event("log", {"source": "agent", "message": f"Task {task.id} done: {summary}"})
                return True

            tool_name = str(action.get("tool", "")).strip()
            args = action.get("args") or {}
            if not tool_name:
                last_observation = "No tool specified. Provide a tool or set 'final': true."
                continue

            observation = await self._run_action(task, tool_name, args)
            last_observation = observation
            await self.memory.add_message("tool", f"{tool_name} -> {observation[:500]}")

        task.error_log.append("Task exceeded its per-task step budget.")
        return False

    async def _decide_action(self, task: Task, last_observation: str) -> dict:
        tools_desc = json.dumps(self.registry.specs(), ensure_ascii=False, indent=2)
        prompt = (
            f"GOAL: {self.goal}\n"
            f"CURRENT TASK ({task.id}): {task.title}\n\n"
            f"AVAILABLE TOOLS:\n{tools_desc}\n\n"
            f"RECENT CONTEXT:\n{self.memory.context_text()[-2000:]}\n\n"
            f"LAST OBSERVATION:\n{last_observation[:2000]}\n\n"
            "Decide the next action."
        )
        raw = await self.llm.complete(_ACTOR_SYSTEM, prompt)
        return extract_json(raw) or {"final": True, "summary": "No actionable response from model."}

    async def _run_action(self, task: Task, tool_name: str, args: dict) -> str:
        """Execute a tool, running TESTING/HEALING flow for shell commands."""
        is_command = tool_name == "run_command"
        if is_command:
            await self._set_state(AgentState.TESTING)

        result = await self.registry.execute(tool_name, **args)

        # Track the most recently written file so the healer knows what to patch.
        if tool_name == "write_file" and result.success:
            self._last_written_file = str(args.get("path", "")) or self._last_written_file

        if result.success:
            self.healer.reset(f"{self._last_written_file}::{args.get('command', '')}")
            return f"OK: {result.output[:1500]}"

        # Failure path -------------------------------------------------------
        error_text = result.error or result.output
        task.error_log.append(f"{tool_name} failed (exit={result.exit_code}): {error_text[:300]}")
        await self._emit_event(
            "error",
            {"source": tool_name, "message": error_text[:800], "exit_code": result.exit_code},
        )

        if is_command and self._last_written_file:
            healed = await self._attempt_healing(task, command=str(args.get("command", "")), stderr=error_text)
            if healed:
                # Retry the original command once after a successful patch.
                retry = await self.registry.execute(tool_name, **args)
                if retry.success:
                    await self._set_state(AgentState.EXECUTING)
                    return f"OK after healing: {retry.output[:1500]}"
                return f"Still failing after healing: {(retry.error or retry.output)[:800]}"

        return f"ERROR (exit={result.exit_code}): {error_text[:800]}"

    async def _attempt_healing(self, task: Task, command: str, stderr: str) -> bool:
        """Iteratively heal the last written file. Returns True if a patch was applied."""
        await self._set_state(AgentState.HEALING)
        filename = self._last_written_file or ""
        try:
            code = await self.env.read_file(filename)
        except (FileNotFoundError, PermissionError) as exc:
            task.error_log.append(f"Healer could not read '{filename}': {exc}")
            return False

        location = f"{filename}::{command}"
        result = await self.healer.heal_code(
            filename=filename, code=code, command=command, stderr=stderr, location=location
        )
        if result.escalated:
            task.error_log.append(f"Healing escalated for '{filename}' after {result.attempts} attempts.")
            return False
        return result.healed

    # ------------------------------------------------------------------ #
    # State helpers
    # ------------------------------------------------------------------ #
    async def _guard(self) -> bool:
        """Honour pause/stop requests. Returns False if the loop must abort."""
        if self._stop_requested:
            await self._set_state(AgentState.FAILED)
            await self._emit_event("log", {"source": "system", "message": "Run stopped by kill-switch."})
            return False
        if not self._resume_event.is_set():
            await self._emit_event("log", {"source": "system", "message": "Paused; awaiting resume."})
            await self._resume_event.wait()
            if self._stop_requested:
                await self._set_state(AgentState.FAILED)
                return False
        return True

    async def _set_state(self, new_state: AgentState) -> None:
        if new_state != self.state:
            logger.info("State transition: %s -> %s", self.state.value, new_state.value)
        self.state = new_state
        await self._emit_event("status", {"state": new_state.value, "iteration": self.iteration_count})
        await self._persist()

    async def _set_task_status(self, task: Task, status: TaskStatus) -> None:
        task.status = status
        logger.info("Task %d '%s' -> %s", task.id, task.title, status.value)
        await self._emit_event("task_update", {"tasks": [t.to_dict() for t in self.task_tree]})
        await self._persist()

    def snapshot(self) -> dict:
        """Return the structured ``agent_state.json`` document."""
        return {
            "current_state": self.state.value,
            "goal": self.goal,
            "iteration_count": self.iteration_count,
            "max_iterations": self.settings.max_iterations,
            "task_tree": [t.to_dict() for t in self.task_tree],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _persist(self) -> None:
        await self.memory.persist_state(self.snapshot())

    async def _emit_event(self, event_type: str, payload: dict) -> None:
        if self._emit is not None:
            await self._emit({"type": event_type, "payload": payload})
