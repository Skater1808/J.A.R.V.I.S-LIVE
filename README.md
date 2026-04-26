# Jarvis V3 — Gemini Live Voice Assistant

Ein deutscher KI-Assistent mit nativer Sprachausgabe. Keine Text-zu-Sprache-Konvertierung, keine externe TTS-API — 100% native Gemini Live Audio.

## Features

- **Rein Audio-basiert**: Spracheingabe → Gemini Live API → Sprachausgabe
- **Eingebaute Tools**: Websuche, Screenshots, URL-Öffnen, Nachrichten
- **MCP Server Unterstützung**: Dateisystem, Zeit, Datenbanken und mehr via Model Context Protocol
- **Deutsche Persönlichkeit**: Charmant, witzig, eloquent mit britischem Understatement
- **Multi-Modal**: Unterstützt Audio + Vision (Screenshots)
- **Echtzeit**: WebSocket-basierte Kommunikation mit Gemini Live

## Schnellstart

### 1. Installation

```bash
# Abhängigkeiten installieren
pip install -r requirements.txt
```

### 2. Konfiguration

```bash
# Setup starten
python setup_jarvis.py
```

`config.json` anpassen:

```json
{
  "gemini_api_key": "DEIN_GEMINI_API_KEY",
  "user_name": "Dein Name",
  "user_address": "Sir",
  "city": "Bremen",
  "jarvis_voice": "Charon"
}
```

**Verfügbare Stimmen**: `Puck` | `Charon` | `Kore` | `Fenrir` | `Aoede`

### 3. Start

```bash
python server.py
```

Dann öffne: http://localhost:8340

**Wichtig**: Auf den Orb klicken, um Audio zu aktivieren (Browser-Policy).

## MCP Server Konfiguration

Jarvis unterstützt MCP (Model Context Protocol) Server für erweiterte Funktionalität.

### Aktive Server

`mcp_servers.json` enthält die aktiven Server:

```json
{
  "servers": [
    {
      "name": "filesystem",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\Users\\DeinUser"],
      "env": {},
      "description": "Dateisystem-Zugriff"
    }
  ]
}
```

### Verfügbare MCP Server

`mcp_servers.example.json` enthält Beispiele für 12 beliebte Server:

| Server | Beschreibung | Installation |
|--------|--------------|--------------|
| `filesystem` | Dateien lesen/schreiben | Auto (npx) |
| `time` | Zeit/Datumsfunktionen | Auto (uvx) |
| `github` | GitHub API Zugriff | Auto (npx) + Token |
| `puppeteer` | Browser-Automation | Auto (npx) |
| `sqlite` | SQLite Datenbank | Auto (uvx) |
| `fetch` | HTTP Requests | Auto (uvx) |
| `brave-search` | Brave Web Search | Auto (npx) + API Key |
| `postgres` | PostgreSQL Datenbank | Auto (npx) |
| `google-maps` | Maps Geocoding | Auto (npx) + API Key |
| `slack` | Slack Integration | Auto (npx) + Token |
| `sentry` | Error Tracking | Auto (npx) + Token |
| `sequential-thinking` | Strukturiertes Denken | Auto (npx) |

**Alle Server werden automatisch installiert** — keine manuelle Installation nötig!

### Server aktivieren

1. Einträge aus `mcp_servers.example.json` kopieren
2. In `mcp_servers.json` einfügen
3. Server neu starten
4. API Keys in `env` konfigurieren (falls nötig)

## Architektur

```
┌─────────────┐     WebSocket        ┌──────────────┐
│   Browser   │ ◄──────────────────► │   Server     │
│  (Frontend) │    Audio/Control     │   (Python)   │
└─────────────┘                      └──────┬───────┘
       │                                  │
       │ WebSocket                        │ WebSocket
       │                                  │
┌──────▼────────┐                  ┌───────▼─────────┐
│  AudioWorklet │                  │  Gemini Live    │
│ (Mic/Playback)│                  │  API (Google)   │
└───────────────┘                  └─────────────────┘
```

### Komponenten

- **`server.py`**: FastAPI WebSocket-Server, Gemini-Kommunikation, Tool-Execution
- **`mcp_client.py`**: MCP Server Verwaltung, Tool-Discovery, Schema-Konvertierung
- **`browser_tools.py`**: Playwright-basierte Browser-Tools (Suche, Screenshots)
- **`frontend/main.js`**: WebSocket-Client, Audio-Capture/Playback, AudioWorklet

## Tools

### Eingebaute Tools

- `search_web(query)` — Websuche via DuckDuckGo
- `open_url(url)` — URL im Browser öffnen
- `take_screenshot()` — Screenshot + Vision-Analyse
- `get_news()` — Aktuelle Nachrichten

### MCP Tools

MCP Server-Tools werden automatisch mit Präfix verfügbar:
- `filesystem__read_file(path)`
- `filesystem__write_file(path, content)`
- `time__get_current_time()`
- etc.

## Entwicklung

### Projektstruktur

```
nummer 4/
├── server.py              # Hauptserver
├── mcp_client.py          # MCP Client Manager
├── browser_tools.py       # Browser-Automation
├── screen_capture.py      # Screenshot-Funktionen
├── config.json            # Konfiguration
├── mcp_servers.json       # Aktive MCP Server
├── mcp_servers.example.json  # Beispiel-Server
├── requirements.txt       # Python-Abhängigkeiten
└── frontend/
    ├── index.html         # UI
    ├── main.js            # Audio-Logik
    └── style.css          # Styling
```

### Wichtige Konfigurationen

| Datei | Zweck |
|-------|-------|
| `config.json` | API-Keys, Nutzerdaten, Voice |
| `mcp_servers.json` | Aktive MCP Server |
| `mcp_servers.example.json` | Verfügbare Server-Beispiele |

## Troubleshooting

### Kein Audio

- **Orb klicken** vor dem Sprechen (Browser-Policy)
- Konsole auf Fehler prüfen
- `audioCtxOut` wird bei ersten Chunk erstellt

### MCP Server Fehler

- Automatische Installation prüfen: `[mcp] uv erfolgreich installiert!`
- Bei Fehlern: Server manuell testen mit `npx -y @modelcontextprotocol/server-XYZ`

### Gemini Verbindung

- API-Key in `config.json` prüfen
- Modell-Verfügbarkeit: `gemini-2.5-flash-native-audio-preview`

## Credits

Built by [Julian](https://skool.com/ki-automatisierung) with [Claude Code](https://claude.ai/code).

Inspired by Iron Man's J.A.R.V.I.S. — *"At your service, Sir."*

---

## License

MIT — use it, modify it, build on it. If you build something cool, let me know!
