"""Jarvis Wiki Tools
Wikipedia, Fandom und Arch Wiki Integration mit 24h Cache.
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

import httpx
import aiosqlite

# Cache database path
CACHE_DB_PATH = Path(__file__).parent / "jarvis_wiki_cache.db"
_cache_initialized = False


async def init_cache_db():
    """Initialize the wiki cache database."""
    conn = await aiosqlite.connect(str(CACHE_DB_PATH))
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS wiki_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT UNIQUE NOT NULL,
            source TEXT NOT NULL,
            title TEXT,
            extract TEXT,
            url TEXT,
            timestamp TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_expires ON wiki_cache(expires_at)
    """)
    await conn.commit()
    await conn.close()


async def get_cached_result(query: str) -> Optional[Dict[str, Any]]:
    """Get cached wiki result if not expired."""
    await ensure_cache_initialized()
    try:
        conn = await aiosqlite.connect(str(CACHE_DB_PATH))
        conn.row_factory = aiosqlite.Row
        
        cursor = await conn.execute("""
            SELECT * FROM wiki_cache 
            WHERE query = ? AND expires_at > ?
        """, (query.lower(), datetime.now().isoformat()))
        
        row = await cursor.fetchone()
        await conn.close()
        
        if row:
            return {
                "source": row["source"],
                "title": row["title"],
                "extract": row["extract"],
                "url": row["url"],
                "cached": True
            }
        return None
    except Exception:
        return None


async def cache_result(query: str, source: str, title: str, extract: str, url: str):
    """Cache wiki result for 24 hours."""
    await ensure_cache_initialized()
    try:
        conn = await aiosqlite.connect(str(CACHE_DB_PATH))
        
        now = datetime.now()
        expires = now + timedelta(hours=24)
        
        await conn.execute("""
            INSERT OR REPLACE INTO wiki_cache 
            (query, source, title, extract, url, timestamp, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (query.lower(), source, title, extract, url, 
              now.isoformat(), expires.isoformat()))
        
        await conn.commit()
        await conn.close()
    except Exception as e:
        print(f"[wiki] Cache error: {e}", flush=True)


async def search_wikipedia(query: str, lang: str = "de") -> Optional[Dict[str, Any]]:
    """Search Wikipedia REST API."""
    # Clean query for URL
    clean_query = re.sub(r'[^\w\s-]', '', query).strip().replace(' ', '_')
    
    urls_to_try = [
        f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{clean_query}",
        f"https://en.wikipedia.org/api/rest_v1/page/summary/{clean_query}"
    ]
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for url in urls_to_try:
            try:
                response = await client.get(url, headers={
                    "User-Agent": "Jarvis-Assistant/1.0"
                })
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("extract"):
                        return {
                            "source": "Wikipedia",
                            "title": data.get("title", query),
                            "extract": data.get("extract", ""),
                            "url": data.get("content_urls", {}).get("desktop", {}).get("page", url),
                            "cached": False
                        }
            except Exception:
                continue
    
    return None


async def search_fandom(query: str, wiki_name: str = "") -> Optional[Dict[str, Any]]:
    """Search Fandom wiki. If wiki_name not specified, try common ones."""
    clean_query = re.sub(r'[^\w\s-]', '', query).strip().replace(' ', '_')
    
    # List of Fandom wikis to try
    fandoms = [wiki_name] if wiki_name else ["minecraft", "starwars", "marvel", "harrypotter"]
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for fandom in fandoms:
            if not fandom:
                continue
            try:
                url = f"https://{fandom}.fandom.com/wiki/{clean_query}"
                response = await client.get(url, headers={
                    "User-Agent": "Jarvis-Assistant/1.0"
                })
                
                if response.status_code == 200:
                    # Simple text extraction from HTML
                    text = response.text
                    # Try to find description
                    desc_match = re.search(r'<meta name="description" content="([^"]+)"', text)
                    if desc_match:
                        return {
                            "source": f"Fandom ({fandom})",
                            "title": query,
                            "extract": desc_match.group(1),
                            "url": url,
                            "cached": False
                        }
            except Exception:
                continue
    
    return None


async def search_arch_wiki(query: str) -> Optional[Dict[str, Any]]:
    """Search Arch Wiki."""
    clean_query = re.sub(r'[^\w\s-]', '', query).strip().replace(' ', '_')
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            # Arch Wiki API endpoint
            url = f"https://wiki.archlinux.org/title/{clean_query}"
            response = await client.get(url, headers={
                "User-Agent": "Jarvis-Assistant/1.0"
            })
            
            if response.status_code == 200:
                text = response.text
                # Extract first paragraph
                desc_match = re.search(r'<p>([^<]+)</p>', text)
                if desc_match:
                    return {
                        "source": "Arch Wiki",
                        "title": query,
                        "extract": desc_match.group(1)[:500],
                        "url": url,
                        "cached": False
                    }
        except Exception:
            pass
    
    return None


async def search_wiki(query: str, wiki_source: str = "auto", config: dict = None) -> Dict[str, Any]:
    """Main wiki search function with caching.
    
    Args:
        query: Search term
        wiki_source: "wikipedia", "fandom", "arch", or "auto"
        config: Configuration dict with optional wiki_sources
    
    Returns:
        Dict with result info or error message
    """
    if not query or not query.strip():
        return {"error": "Kein Suchbegriff angegeben"}
    
    query = query.strip()
    
    # Check cache first
    cached = await get_cached_result(query)
    if cached:
        cached["from_cache"] = True
        return cached
    
    result = None
    
    # Try specified source or auto
    if wiki_source in ("auto", "wikipedia"):
        result = await search_wikipedia(query, lang="de")
        if not result and wiki_source == "wikipedia":
            # Try English as fallback
            result = await search_wikipedia(query, lang="en")
    
    if not result and wiki_source in ("auto", "fandom"):
        # Get configured fandoms from config
        fandoms = []
        if config and "wiki_sources" in config:
            fandoms = config["wiki_sources"].get("fandom", [])
        
        for fandom in fandoms:
            result = await search_fandom(query, fandom)
            if result:
                break
        
        # If no specific fandoms configured, try auto
        if not result and wiki_source == "auto" and not fandoms:
            result = await search_fandom(query)
    
    if not result and wiki_source in ("auto", "arch"):
        result = await search_arch_wiki(query)
    
    if result:
        # Cache the result
        await cache_result(query, result["source"], result["title"], 
                          result["extract"], result["url"])
        return result
    
    # No result found
    return {
        "error": "Kein Wiki-Eintrag gefunden",
        "fallback_suggestion": "Soll ich im Internet danach suchen?"
    }


async def get_recent_searches(limit: int = 5) -> list:
    """Get recent wiki searches from cache."""
    try:
        conn = await aiosqlite.connect(str(CACHE_DB_PATH))
        conn.row_factory = aiosqlite.Row
        
        cursor = await conn.execute("""
            SELECT query, source, title, timestamp 
            FROM wiki_cache 
            ORDER BY timestamp DESC 
            LIMIT ?
        """, (limit,))
        
        rows = await cursor.fetchall()
        await conn.close()
        
        return [{
            "query": row["query"],
            "source": row["source"],
            "title": row["title"],
            "timestamp": row["timestamp"]
        } for row in rows]
    except Exception:
        return []


async def ensure_cache_initialized():
    """Ensure cache DB is initialized (call before using cache)."""
    global _cache_initialized
    if not _cache_initialized:
        await init_cache_db()
        _cache_initialized = True
