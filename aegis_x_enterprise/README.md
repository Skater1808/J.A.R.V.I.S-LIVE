# Aegis-X Enterprise

An autonomous, asynchronous AI software-engineering agent with a real-time web
control center, a dynamic plugin system and a Hermes-style iterative
self-healing engine.

## Highlights

- **Async ReAct core loop** driven by a strict finite state machine
  (`IDLE → PLANNING → EXECUTING → TESTING → HEALING → COMPLETED / FAILED`).
- **Sandboxed execution** — every file and shell operation is locked inside
  `./workspace/` via a central `validate_path()` guard, and every command runs
  under a hard timeout (default 45s).
- **Hermes self-healing** — failing commands/tests trigger an LLM reflection
  loop that patches the offending file, escalating to `FAILED` after 3
  unsuccessful attempts at the same location.
- **Dynamic plugins** — drop a `*.py` file into `plugins/` and it is discovered
  and loaded at boot via `importlib`. A working `sample_plugin.py` (weather) is
  included.
- **Real-time UI** — FastAPI + WebSockets stream every state change, log line
  and task update to a single-file Tailwind dashboard.
- **Multi-provider** — OpenAI (GPT-4o), Anthropic (Claude 3.5 Sonnet), Google
  Gemini (1.5 Pro) and local Ollama, selected interactively in setup.

## Quick start

```bash
cd aegis_x_enterprise
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python setup.py          # interactive: pick provider, enter key, write .env
python main.py           # serves the dashboard on http://127.0.0.1:8000
```

Open <http://127.0.0.1:8000>, type a goal, and press **Start**.

> Without credentials the agent runs in a deterministic **offline** mode so the
> full state machine, UI and plugin system remain demonstrable.

## WebSocket protocol

Every frame pushed to `/ws/logs` follows:

```json
{ "type": "status|log|task_update|error", "payload": { }, "timestamp": "ISO-8601" }
```

## REST endpoints

| Method | Path      | Description                          |
|--------|-----------|--------------------------------------|
| GET    | `/`       | Tailwind dashboard                   |
| POST   | `/start`  | `{ "goal": "..." }` — start a run    |
| POST   | `/pause`  | toggle pause / resume                |
| POST   | `/stop`   | emergency kill-switch                |
| GET    | `/state`  | current structured agent state       |
| WS     | `/ws/logs`| real-time event stream               |

## Project layout

```
aegis_x_enterprise/
├── setup.py            # interactive provider/install assistant
├── config.py           # pydantic-settings v2 + LLM client abstraction
├── main.py             # entry point (logging + uvicorn)
├── agent/
│   ├── core.py         # async ReAct loop & state machine
│   ├── memory.py       # SQLite + JSON state persistence
│   └── healer.py       # Hermes error analysis & code patching
├── execution/
│   └── local_env.py    # sandboxed subprocess runner + validate_path
├── tools/
│   ├── base.py         # BaseTool / BasePlugin abstractions
│   └── registry.py     # file-system, HTTP and terminal tools
├── plugins/
│   ├── manager.py      # dynamic importlib-based loader
│   └── sample_plugin.py# working example plugin (weather)
├── ui/
│   ├── app.py          # FastAPI app, REST routes & WebSocket server
│   └── templates/index.html  # monolithic Tailwind dashboard
└── workspace/          # isolated agent sandbox
```
