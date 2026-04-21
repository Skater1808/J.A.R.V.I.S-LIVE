"""
Jarvis V3 — Gemini Live Edition
Real-time audio: Mic -> Gemini Live API -> Speaker
No text conversion, no ElevenLabs — 100% native voice.
"""

import asyncio
import json
import os
import time

import google.generativeai as genai
import httpx
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# ── Config ─────────────────────────────────────────────────────────────
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
with open(CONFIG_PATH) as f:
    config = json.load(f)

GEMINI_API_KEY = config["gemini_api_key"]
USER_NAME      = config.get("user_name",    "Emil Carstensen")
USER_ADDRESS   = config.get("user_address", "Sir")
CITY           = config.get("city",         "Bremen")
TASKS_FILE     = config.get("obsidian_inbox_path", "")
JARVIS_VOICE   = config.get("jarvis_voice", "Charon")
# Available voices: Puck | Charon | Kore | Fenrir | Aoede

GEMINI_LIVE_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1alpha."
    f"GenerativeService.BidiGenerateContent?key={GEMINI_API_KEY}"
)

# Vision model for screenshot descriptions (non-live)
genai.configure(api_key=GEMINI_API_KEY)
vision_model = genai.GenerativeModel("gemini-2.0-flash-exp")

http = httpx.AsyncClient(timeout=30)
app  = FastAPI()

import browser_tools
import screen_capture


# ── Weather / Tasks ─────────────────────────────────────────────────────
WEATHER_INFO = None
TASKS_INFO   = []

def _fetch_weather():
    import urllib.request
    try:
        req  = urllib.request.Request(
            f"https://wttr.in/{CITY}?format=j1",
            headers={"User-Agent": "curl"},
        )
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read())
        c    = data["current_condition"][0]
        return {
            "temp":        c["temp_C"],
            "feels_like":  c["FeelsLikeC"],
            "description": c["weatherDesc"][0]["value"],
            "humidity":    c["humidity"],
            "wind_kmh":    c["windspeedKmph"],
        }
    except Exception:
        return None

def _fetch_tasks():
    if not TASKS_FILE:
        return []
    try:
        with open(os.path.join(TASKS_FILE, "Tasks.md"), encoding="utf-8") as f:
            lines = f.readlines()
        return [
            l.strip().replace("- [ ]", "").strip()
            for l in lines if l.strip().startswith("- [ ]")
        ]
    except Exception:
        return []

def refresh_data():
    global WEATHER_INFO, TASKS_INFO
    WEATHER_INFO = _fetch_weather()
    TASKS_INFO   = _fetch_tasks()
    print(f"[jarvis] Wetter: {WEATHER_INFO}", flush=True)
    print(f"[jarvis] Tasks : {len(TASKS_INFO)} geladen", flush=True)

refresh_data()


# ── System Prompt ────────────────────────────────────────────────────────
def build_system_prompt() -> str:
    weather = ""
    if WEATHER_INFO:
        w = WEATHER_INFO
        weather = (
            f"\nWetter {CITY}: {w['temp']}C, "
            f"gefuehlt {w['feels_like']}C, {w['description']}"
        )
    tasks = ""
    if TASKS_INFO:
        tasks = (
            f"\nOffene Aufgaben ({len(TASKS_INFO)}): "
            + ", ".join(TASKS_INFO[:5])
        )

    return (
        f"Du bist Jarvis, der KI-Assistent von {USER_NAME}. "
        f"Du sprichst ausschliesslich Deutsch. "
        f"{USER_NAME} wird mit {USER_ADDRESS} angesprochen und gesiezt. "
        f"Dein Ton ist trocken, sarkastisch, britisch-hoeflich. "
        f"Kurze Antworten, maximal 3 Saetze. Kein Markdown. "
        f"Du kannst Browser steuern, Bildschirm sehen und News abrufen. "
        f"Nutze Funktionen direkt ohne zu fragen. "
        f"Aktuelle Zeit: {time.strftime('%H:%M')}. "
        f"=== DATEN ==={weather}{tasks} === "
        f"Wenn Nutzer 'Jarvis activate' sagt: begruesse passend zur Tageszeit, "
        f"nenne kurz Wetter und Aufgaben, ende humorvoll."
    )


# ── Tool Declarations ────────────────────────────────────────────────────
FUNCTION_DECLARATIONS = [
    {
        "name": "search_web",
        "description": "Sucht im Internet nach Informationen",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Suchbegriff"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "open_url",
        "description": "Oeffnet eine URL im Browser",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "url": {"type": "STRING", "description": "Vollstaendige URL"}
            },
            "required": ["url"],
        },
    },
    {
        "name": "take_screenshot",
        "description": "Screenshot des Bildschirms machen und beschreiben",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "get_news",
        "description": "Aktuelle Weltnachrichten abrufen",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
]


# ── Tool Execution ───────────────────────────────────────────────────────
async def execute_tool(name: str, args: dict) -> str:
    print(f"  [tool] {name}({args})", flush=True)
    try:
        if name == "search_web":
            result = await browser_tools.search_and_read(args.get("query", ""))
            if "error" not in result:
                return (
                    f"Seite: {result.get('title', '')}\n"
                    f"{result.get('content', '')[:1800]}"
                )
            return "Suche fehlgeschlagen."

        elif name == "open_url":
            await browser_tools.open_url(args.get("url", ""))
            return f"Geoeffnet: {args.get('url', '')}"

        elif name == "take_screenshot":
            return await screen_capture.describe_screen_gemini(vision_model)

        elif name == "get_news":
            return await browser_tools.fetch_news()

    except Exception as e:
        return f"Fehler: {e}"
    return "Unbekannte Funktion."


# ── Gemini Live Setup Message ────────────────────────────────────────────
def build_setup_msg(system_prompt: str) -> str:
    return json.dumps({
        "setup": {
            "model": "models/gemini-2.0-flash-live-001",
            "generation_config": {
                "response_modalities": ["AUDIO"],
                "speech_config": {
                    "voice_config": {
                        "prebuilt_voice_config": {
                            "voice_name": JARVIS_VOICE
                        }
                    }
                },
            },
            "system_instruction": {
                "parts": [{"text": system_prompt}]
            },
            "tools": [{"function_declarations": FUNCTION_DECLARATIONS}],
        }
    })


# ── WebSocket endpoint ───────────────────────────────────────────────────
@app.websocket("/ws")
async def ws_endpoint(browser_ws: WebSocket):
    await browser_ws.accept()
    cid = id(browser_ws)
    print(f"[ws] Client {cid} verbunden", flush=True)

    refresh_data()

    try:
        async with websockets.connect(
            GEMINI_LIVE_URL,
            additional_headers={"Content-Type": "application/json"},
            max_size=10 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=60,
        ) as gemini_ws:

            # Handshake
            await gemini_ws.send(build_setup_msg(build_system_prompt()))
            raw = await asyncio.wait_for(gemini_ws.recv(), timeout=10)
            resp = json.loads(raw)
            if "setupComplete" in resp:
                print("[gemini] Setup OK", flush=True)
            else:
                print(f"[gemini] Setup-Antwort: {resp}", flush=True)

            # Greeting trigger
            await gemini_ws.send(json.dumps({
                "client_content": {
                    "turns": [{
                        "role":  "user",
                        "parts": [{"text": "Jarvis activate"}],
                    }],
                    "turn_complete": True,
                }
            }))
            await browser_ws.send_json({"type": "status", "text": "Jarvis aktiv — ich hoere zu..."})

            # ── browser → Gemini ──────────────────────────────────────────
            async def browser_to_gemini():
                try:
                    while True:
                        msg = await browser_ws.receive_json()
                        if msg.get("type") == "audio":
                            await gemini_ws.send(json.dumps({
                                "realtime_input": {
                                    "media_chunks": [{
                                        "mime_type": "audio/pcm;rate=16000",
                                        "data":      msg["data"],
                                    }]
                                }
                            }))
                except Exception:
                    pass

            # ── Gemini → browser ──────────────────────────────────────────
            async def gemini_to_browser():
                try:
                    async for raw_msg in gemini_ws:
                        msg = json.loads(raw_msg)

                        # Audio chunks
                        if "serverContent" in msg:
                            sc = msg["serverContent"]
                            for part in sc.get("modelTurn", {}).get("parts", []):
                                if "inlineData" in part:
                                    await browser_ws.send_json({
                                        "type": "audio",
                                        "data": part["inlineData"]["data"],
                                    })
                                if "text" in part and part["text"].strip():
                                    await browser_ws.send_json({
                                        "type": "transcript",
                                        "text": part["text"].strip(),
                                    })
                            if sc.get("turnComplete"):
                                await browser_ws.send_json({"type": "turn_complete"})
                            if sc.get("interrupted"):
                                await browser_ws.send_json({"type": "interrupted"})

                        # Tool calls
                        elif "toolCall" in msg:
                            calls     = msg["toolCall"].get("functionCalls", [])
                            responses = []
                            for call in calls:
                                result = await execute_tool(
                                    call["name"], call.get("args", {})
                                )
                                responses.append({
                                    "id":       call["id"],
                                    "response": {"result": result},
                                })
                            await gemini_ws.send(json.dumps({
                                "tool_response": {
                                    "function_responses": responses
                                }
                            }))
                except Exception:
                    pass

            t1 = asyncio.create_task(browser_to_gemini())
            t2 = asyncio.create_task(gemini_to_browser())
            done, pending = await asyncio.wait(
                [t1, t2], return_when=asyncio.FIRST_EXCEPTION
            )
            for t in pending:
                t.cancel()

    except WebSocketDisconnect:
        print(f"[ws] Client {cid} getrennt", flush=True)
    except Exception as e:
        print(f"[ws] Fehler: {e}", flush=True)
        try:
            await browser_ws.send_json({"type": "error", "text": str(e)})
        except Exception:
            pass


# ── Static & Entry ───────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.get("/")
async def index():
    return FileResponse("frontend/index.html")


if __name__ == "__main__":
    import uvicorn
    print(f"\n{'='*58}")
    print(f"  JARVIS V3  —  Gemini Live Edition")
    print(f"  http://localhost:8340")
    print(f"  Nutzer : {USER_NAME} ({USER_ADDRESS})")
    print(f"  Stadt  : {CITY}")
    print(f"  Stimme : {JARVIS_VOICE}")
    print(f"  Modell : gemini-2.0-flash-live-001")
    print(f"  Kein ElevenLabs benoetigt!")
    print(f"{'='*58}\n")
    uvicorn.run(app, host="0.0.0.0", port=8340, log_level="warning")