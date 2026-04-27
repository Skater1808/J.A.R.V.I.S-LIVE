"""Jarvis Quick Notes System
Schnelle Sprachnotizen mit Datei-Speicherung und SQLite-Fallback.
"""

import os
import re
import aiosqlite
from datetime import datetime
from pathlib import Path
from typing import Optional

# Import DB_PATH from memory module
from memory import DB_PATH as MEMORY_DB_PATH

# Default notes file name
DEFAULT_NOTES_FILENAME = "JarvisQuickNotes.md"


async def get_notes_path(config: dict) -> Path:
    """Determine the notes file path from config."""
    # Priority 1: Explicit quick_notes_path
    if config.get("quick_notes_path"):
        path = Path(config["quick_notes_path"])
        # Ensure directory exists
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    
    # Priority 2: Obsidian inbox path
    if config.get("obsidian_inbox_path"):
        inbox = Path(config["obsidian_inbox_path"])
        if inbox.is_dir():
            return inbox / DEFAULT_NOTES_FILENAME
        else:
            # If obsidian_inbox_path is a file, use its directory
            inbox.parent.mkdir(parents=True, exist_ok=True)
            return inbox.parent / DEFAULT_NOTES_FILENAME
    
    # Priority 3: Default in workspace or home
    workspace = config.get("workspace_path", "")
    if workspace:
        path = Path(workspace) / DEFAULT_NOTES_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    
    # Fallback: Home directory
    home = Path.home()
    return home / "Documents" / DEFAULT_NOTES_FILENAME


def extract_category(note_text: str) -> tuple[str, str]:
    """Extract category from note text if present.
    
    Returns (category, clean_text) where category can be:
    - Extracted from "unter KATEGORIE: text" or "bei KATEGORIE: text"
    - "Ideas", "Shopping", "Work", "Personal", etc.
    """
    # Pattern: "unter X: " or "bei X: " or "in X: "
    patterns = [
        r"unter\s+(\w+):?\s*",
        r"bei\s+(\w+):?\s*",
        r"in\s+(\w+):?\s*",
    ]
    
    for pattern in patterns:
        match = re.search(pattern, note_text, re.IGNORECASE)
        if match:
            category = match.group(1).capitalize()
            # Remove the category marker from text
            clean_text = re.sub(pattern, "", note_text, flags=re.IGNORECASE, count=1).strip()
            return category, clean_text
    
    # Auto-detect category from content
    text_lower = note_text.lower()
    if any(word in text_lower for word in ["kaufen", "einkauf", "milch", "brot", "supermarkt"]):
        return "Shopping", note_text
    elif any(word in text_lower for word in ["idee", "konzept", "feature", "plan", "projekt"]):
        return "Ideas", note_text
    elif any(word in text_lower for word in ["termin", "besprechung", "meeting", "um ", "uhr"]):
        return "Termine", note_text
    
    return "Allgemein", note_text


def get_category_filename(base_path: Path, category: str) -> Path:
    """Get filename for a specific category."""
    if category == "Allgemein":
        return base_path
    
    # Create category-specific file in same directory
    dir_path = base_path.parent
    safe_category = re.sub(r'[^\w\-]', '_', category)
    return dir_path / f"JarvisNotes_{safe_category}.md"


async def append_to_file(file_path: Path, note_text: str) -> bool:
    """Append a note to the markdown file with timestamp."""
    try:
        now = datetime.now()
        date_header = now.strftime("## %Y-%m-%d %H:%M")
        time_bullet = now.strftime("%H:%M")
        
        # Read existing content if file exists
        existing_content = ""
        if file_path.exists():
            try:
                existing_content = file_path.read_text(encoding='utf-8')
            except Exception:
                existing_content = ""
        
        # Check if we already have this date header
        if date_header in existing_content:
            # Append to existing date section
            lines = existing_content.split('\n')
            new_lines = []
            date_found = False
            for line in lines:
                new_lines.append(line)
                if line.strip() == date_header:
                    date_found = True
                elif date_found and line.startswith('## '):
                    # Next date header, insert before
                    new_lines.insert(-1, f"- {note_text}")
                    date_found = False
            
            if date_found:
                # End of file, append
                new_lines.append(f"- {note_text}")
            
            content = '\n'.join(new_lines)
        else:
            # Add new date section
            if existing_content.strip():
                content = existing_content.rstrip() + f"\n\n{date_header}\n\n- {note_text}\n"
            else:
                content = f"# Jarvis Notizen\n\n{date_header}\n\n- {note_text}\n"
        
        # Write back
        file_path.write_text(content, encoding='utf-8')
        return True
        
    except Exception as e:
        print(f"[quick_notes] File write error: {e}", flush=True)
        return False


async def save_to_sqlite(note_text: str, category: str = "Allgemein") -> bool:
    """Fallback: Save note to SQLite database."""
    try:
        conn = await aiosqlite.connect(str(MEMORY_DB_PATH))
        
        # Ensure table exists
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS quick_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                category TEXT,
                note_text TEXT NOT NULL
            )
        """)
        
        now = datetime.now().isoformat()
        await conn.execute("""
            INSERT INTO quick_notes (timestamp, category, note_text)
            VALUES (?, ?, ?)
        """, (now, category, note_text))
        
        await conn.commit()
        await conn.close()
        return True
        
    except Exception as e:
        print(f"[quick_notes] SQLite error: {e}", flush=True)
        return False


async def add_quick_note(note_text: str, config: dict) -> str:
    """Main function to add a quick note.
    
    Returns success message or error message.
    """
    if not note_text or not note_text.strip():
        return "Sir, ich habe keine Notiz verstanden."
    
    # Extract category and clean text
    category, clean_text = extract_category(note_text)
    
    # Get the appropriate file path
    base_path = await get_notes_path(config)
    file_path = get_category_filename(base_path, category)
    
    # Ensure directory exists
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[quick_notes] Cannot create directory: {e}", flush=True)
        # Fallback to SQLite
        success = await save_to_sqlite(clean_text, category)
        if success:
            return f"Notiert in Datenbank (Kategorie: {category})."
        return "Sir, ich kann nicht auf die Notizendatei zugreifen."
    
    # Try to write to file
    success = await append_to_file(file_path, clean_text)
    
    if success:
        if category != "Allgemein":
            return f"Gespeichert unter {category}, Sir."
        return "Gespeichert, Sir."
    else:
        # Fallback to SQLite
        success = await save_to_sqlite(clean_text, category)
        if success:
            return f"Notiert in Datenbank (Kategorie: {category})."
        return "Sir, ich kann nicht auf die Notizendatei zugreifen."


async def get_recent_notes(limit: int = 10, config: dict = None) -> list:
    """Get recent notes from file or database."""
    notes = []
    
    # Try file first
    if config:
        base_path = await get_notes_path(config)
        if base_path.exists():
            try:
                content = base_path.read_text(encoding='utf-8')
                # Parse markdown for recent entries
                lines = content.split('\n')
                for line in lines:
                    if line.strip().startswith('- '):
                        notes.append(line.strip()[2:])
                        if len(notes) >= limit:
                            break
            except Exception:
                pass
    
    # If no file notes, try database
    if not notes:
        try:
            conn = await aiosqlite.connect(str(MEMORY_DB_PATH))
            conn.row_factory = aiosqlite.Row
            
            cursor = await conn.execute("""
                SELECT timestamp, category, note_text 
                FROM quick_notes 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (limit,))
            
            rows = await cursor.fetchall()
            await conn.close()
            
            for row in rows:
                notes.append(f"[{row['category']}] {row['note_text']}")
                
        except Exception:
            pass
    
    return notes
