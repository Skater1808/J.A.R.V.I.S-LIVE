#!/usr/bin/env python3
"""
Jarvis V3 — Setup Wizard (Gemini Live Edition)
Alles kostenlos. Kein ElevenLabs. Direkte Sprachausgabe via Gemini.
"""

import json
import os
import sys
import subprocess


def header(text):
    print("\n" + "=" * 58)
    print(f"  {text}")
    print("=" * 58 + "\n")


def ask(prompt, default=None, required=True):
    while True:
        full = f"{prompt} [{default}]: " if default else f"{prompt}: "
        val  = input(full).strip()
        if not val and default:
            return default
        if not val and required:
            print("  ⚠  Pflichtfeld!")
            continue
        return val or None


def check_python():
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 10):
        print(f"  ❌ Python 3.10+ benötigt (Aktuell: {v.major}.{v.minor})")
        sys.exit(1)
    print(f"  ✅ Python {v.major}.{v.minor}")


def check_chrome():
    paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for p in paths:
        if os.path.exists(p):
            print("  ✅ Google Chrome gefunden")
            return True
    print("  ⚠  Chrome nicht gefunden → https://www.google.com/chrome/")
    return False


def install_deps():
    print("\n  Installiere Python-Pakete...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q"],
        check=True,
    )
    print("  ✅ Pakete installiert")

    print("  Installiere Playwright Chromium...")
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=True,
    )
    print("  ✅ Playwright Chromium installiert")


def select_voice():
    voices = {
        "1": ("Charon",   "Tief, dunkel — klassischer Butler"),
        "2": ("Puck",     "Jung, frisch — lebhaft"),
        "3": ("Fenrir",   "Rau, stark — markant"),
        "4": ("Kore",     "Klar, weiblich — präzise"),
        "5": ("Aoede",    "Sanft, weiblich — melodisch"),
    }
    print("  Gemini-Stimmen (keine Extra-Kosten!):\n")
    for k, (name, desc) in voices.items():
        print(f"    {k}. {name:10} — {desc}")
    print()
    choice = ask("  Deine Wahl (1-5)", default="1")
    return voices.get(choice, voices["1"])[0]


def main():
    header("🤖 JARVIS V3  —  Setup Wizard (Gemini Live)")

    # ── Schritt 0: Voraussetzungen ────────────────────────────────────────
    header("Schritt 0 · Voraussetzungen")
    check_python()
    check_chrome()
    install_deps()

    # ── Schritt 1: Nutzer-Info ────────────────────────────────────────────
    header("Schritt 1 · Deine Angaben")
    name    = ask("Dein Name", required=True)
    address = ask("Anrede durch Jarvis (z.B. Sir, Chef, Herr)", default="Sir")
    city    = ask("Stadt für Wetter", default="Hamburg")

    # ── Schritt 2: API-Key ────────────────────────────────────────────────
    header("Schritt 2 · Gemini API Key (KOSTENLOS!)")
    print("  Hol dir deinen Key hier — kein Kreditkarte nötig:")
    print("  → https://aistudio.google.com/app/apikey")
    print("  → Klicke 'Create API key'")
    print()
    gemini_key = ask("  Gemini API Key", required=True)

    # ── Schritt 3: Stimme ─────────────────────────────────────────────────
    header("Schritt 3 · Jarvis-Stimme")
    voice = select_voice()

    # ── Schritt 4: Apps & Website ─────────────────────────────────────────
    header("Schritt 4 · Autostart-Apps (beim Doppelklatschen)")
    print("  Beispiele: code  |  obsidian://open  |  explorer")
    apps_raw = ask("  Apps (kommagetrennt)", default="code")
    apps     = [a.strip() for a in apps_raw.split(",") if a.strip()]

    header("Schritt 5 · Browser-Startseite")
    browser_url = ask("  URL", default="https://www.google.com")

    header("Schritt 6 · Spotify (optional)")
    spotify_raw = ask("  Spotify Track URI (leer = überspringen)", required=False)
    spotify     = spotify_raw if spotify_raw else ""

    header("Schritt 7 · Obsidian Vault (optional)")
    use_obs = input("  Obsidian integrieren? (j/n) [n]: ").strip().lower()
    obsidian = ""
    if use_obs == "j":
        obsidian = ask("  Pfad zum Inbox-Ordner", required=False) or ""

    # ── Config erstellen ───────────────────────────────────────────────────
    header("Config wird erstellt...")
    workspace = os.path.dirname(os.path.abspath(__file__))
    cfg = {
        "gemini_api_key":     gemini_key,
        "user_name":          name,
        "user_address":       address,
        "city":               city,
        "jarvis_voice":       voice,
        "workspace_path":     workspace,
        "browser_url":        browser_url,
        "spotify_track":      spotify,
        "apps":               apps,
        "obsidian_inbox_path": obsidian,
    }
    cfg_path = os.path.join(workspace, "config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    print(f"  ✅ config.json gespeichert")

    # ── server.py Defaults patchen ─────────────────────────────────────────
    srv = os.path.join(workspace, "server.py")
    with open(srv, encoding="utf-8") as f:
        code = f.read()
    code = code.replace('config.get("user_name",    "Emil")',    f'config.get("user_name",    "{name}")')
    code = code.replace('config.get("user_address", "Sir")',     f'config.get("user_address", "{address}")')
    code = code.replace('config.get("city",         "Hamburg")', f'config.get("city",         "{city}")')
    code = code.replace('config.get("jarvis_voice", "Charon")',  f'config.get("jarvis_voice", "{voice}")')
    with open(srv, "w", encoding="utf-8") as f:
        f.write(code)
    print("  ✅ server.py angepasst")

    # ── Fertig ─────────────────────────────────────────────────────────────
    print(f"\n{'='*58}")
    print(f"  🎉 Setup abgeschlossen! Willkommen, {name}!")
    print(f"{'='*58}")
    print(f"""
  Stimme  : {voice}
  Stadt   : {city}
  Anrede  : {address}
  KI      : Gemini Live (kostenlos!)
  Kosten  : €0,00 / Monat

  ── JARVIS STARTEN ──────────────────────────────────

  1. Server starten:
       python server.py

  2. Chrome öffnen:
       http://localhost:8340

  3. Den Orb klicken → Mikrofon erlauben → sprechen!

  ── MIT DOPPELKLATSCHEN ─────────────────────────────

       python scripts\\clap-trigger.py
       (Zweimal klatschen → alles startet)

  ── STIMME WECHSELN ─────────────────────────────────
  config.json → "jarvis_voice": "Puck" / "Fenrir" / ...

  ── TIPPS ───────────────────────────────────────────
  "Wie ist das Wetter?"
  "Such nach Python Tutorials"
  "Öffne GitHub"
  "Was siehst du auf meinem Bildschirm?"

  💡 Kein ElevenLabs, kein Anthropic — nur Gemini!
""")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  Setup abgebrochen.")
    except Exception as e:
        print(f"\n  Setup fehlgeschlagen: {e}")