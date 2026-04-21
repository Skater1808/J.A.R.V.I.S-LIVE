# 🤖 JARVIS V3 — Gemini Live + ElevenLabs

Ein persönlicher KI-Sprachassistent mit echter Sprach-Konversation.

**Mic → Gemini Live → Text → ElevenLabs TTS → Speaker**

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
2. **ElevenLabs**: https://elevenlabs.io/profile (10k chars/Monat gratis)

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
    └── launch-session.ps1
```

## 🎯 Features

✅ Live Voice Input (PCM 16kHz)
✅ Gemini Live Conversation
✅ ElevenLabs Streaming TTS
✅ Browser Control (Google Search, URLs)
✅ Screenshot Analysis
✅ Weather + Tasks
✅ Tool Calling (search, open, screenshot, news)

## 💰 Kosten

- Gemini API: **Kostenlos** (60 req/min)
- ElevenLabs: **Kostenlos** (10k chars/monat)
- **Total: €0,00/Monat**

## 🔧 Konfiguration

In `config.json`:

```json
{
  "gemini_api_key": "...",
  "elevenlabs_api_key": "...",
  "elevenlabs_voice_id": "rDmv3mOhK6TnhYWckFaD",
  "user_name": "Emil",
  "user_address": "Sir",
  "city": "Hamburg"
}
```

ElevenLabs Voice IDs:
- `rDmv3mOhK6TnhYWckFaD` - Felix (deutsch, präzise)
- `EXAVITQu4vr4xnSDxMaL` - Bella (weiblich, natürlich)
- `21m00Tcm4TlvDq8ikWAM` - Rachel (englisch)

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
| Kein Audio | ElevenLabs Key überprüfen, Chrome Sound-Einstellungen |
| Mikrofon geht nicht | `chrome://settings/content/microphone` → "Zulassen" |
| Port 8340 belegt | Andere App beenden oder `set JARVIS_PORT=8341` |

## 📖 Mehr Infos

- Gemini Docs: https://ai.google.dev
- ElevenLabs: https://elevenlabs.io
- Playwright: https://playwright.dev

---

**Viel Spaß mit Jarvis! 🎉**
