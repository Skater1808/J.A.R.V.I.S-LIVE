# 🤖 JARVIS V3 — Gemini Live 

Ein persönlicher KI-Sprachassistent mit echter Sprach-Konversation.

**Mic → Gemini Live → Speaker**

## ⚡ Quick Start

```bash
# 1. Setup
python setup_jarvis.py

# 2. Server
python server.py

# 3. Browser
http://localhost:8340
# Klick Orb → Sprechen!
```

## 🔑 API-Keys

1. **Gemini**: https://aistudio.google.com/app/apikey (kostenlos)

## 💬 Befehle

```
"Wie ist das Wetter?"
"Such nach Python Tutorials"
"Öffne GitHub.com"
"Was siehst du auf meinem Bildschirm?"
"Zeig meine Aufgaben"
```

## 📁 Struktur

```
jarvis-voice-assistant/
├── server.py              ← FastAPI + Gemini Live
├── setup_jarvis.py        ← Interaktives Setup
├── requirements.txt       ← Dependencies
├── config.example.json    ← Template
├── config.json            ← Deine Config (wird erstellt)
├── browser_tools.py       ← Browser Automation
├── screen_capture.py      ← Screenshot Vision
├── frontend/
│   ├── index.html
│   ├── main.js           ← Mic Capture + Audio Playback
│   └── style.css
└── scripts/
    ├── clap-trigger.py
```

## 🎯 Features

✅ Live Voice Input (PCM 16kHz)
✅ Gemini Live Conversation
✅ Browser Control (Google Search, URLs)
✅ Screenshot Analysis
✅ Weather + Tasks
✅ Tool Calling (search, open, screenshot, news)

## 💰 Kosten

- Gemini API: **Kostenlos** (60 req/min)
- **Total: €0,00/Monat**

## 🔧 Konfiguration

In `config.json`:

```json
{
  "gemini_api_key": "...",
  "user_name": "Emil",
  "user_address": "Sir",
  "city": "Hamburg"
}
```

## 👏 Mit Doppelklatschen starten

```bash
python scripts/clap-trigger.py
# Zweimal klatschen → Chrome + Code + Obsidian + Jarvis starten
```

## 🛠️ Windows Task Scheduler

Autostart einrichten:
1. `Win + R` → `taskschd.msc`
2. "Aufgabe erstellen"
3. Trigger: "Bei Anmeldung"
4. Aktion: `powershell -ExecutionPolicy Bypass -WindowStyle Hidden -Command "python C:\path\to\clap-trigger.py"`

## 📞 Troubleshooting

| Problem | Lösung |
|---------|--------|
| Gemini API Error | API Key prüfen + neu erstellen |
| Mikrofon geht nicht | `chrome://settings/content/microphone` → "Zulassen" |
| Port 8340 belegt | Andere App beenden oder `set JARVIS_PORT=8341` |

## 📖 Mehr Infos

- Gemini Docs: https://ai.google.dev
- Playwright: https://playwright.dev

---

**Viel Spaß mit Jarvis! 🎉**



## Credits

Built by [Julian](https://skool.com/ki-automatisierung) with [Claude Code](https://claude.ai/code).

Inspired by Iron Man's J.A.R.V.I.S. — *"At your service, Sir."*

---
