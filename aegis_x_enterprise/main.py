"""Aegis-X Enterprise entry point.

Configures colourful structured logging, builds the FastAPI application (which
wires the entire agent stack and starts the plugin manager on the lifespan
startup hook) and serves it with Uvicorn.

Usage::

    python main.py
"""

from __future__ import annotations

import logging

import uvicorn

from config import get_settings
from ui.app import create_app


def configure_logging(level: str = "INFO") -> None:
    """Install a colourful logging handler (rich if available, else plain)."""
    try:
        from rich.logging import RichHandler

        handler: logging.Handler = RichHandler(rich_tracebacks=True, show_path=False, markup=True)
        fmt = "%(message)s"
    except Exception:  # noqa: BLE001 - rich is optional
        handler = logging.StreamHandler()
        fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        datefmt="[%X]",
        handlers=[handler],
        force=True,
    )


# Expose a module-level ``app`` so ``uvicorn ui.app:app``-style invocation and
# the WSGI/ASGI ecosystem can import it directly.
settings = get_settings()
configure_logging(settings.log_level)
app = create_app(settings)


def main() -> None:
    logging.getLogger("aegis").info(
        "Starting Aegis-X Enterprise on http://%s:%s", settings.host, settings.port
    )
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level.lower())


if __name__ == "__main__":
    main()
