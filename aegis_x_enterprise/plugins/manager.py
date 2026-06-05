"""Dynamic plugin discovery and loading.

The :class:`PluginManager` scans the ``plugins/`` directory at boot, dynamically
imports every ``*.py`` module via :mod:`importlib`, instantiates any concrete
subclass of :class:`~tools.base.BasePlugin` it finds, and lets each plugin
register its tools against the shared :class:`~tools.registry.ToolRegistry`.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import logging
import sys
from pathlib import Path

from tools.base import BasePlugin
from tools.registry import ToolRegistry

logger = logging.getLogger("aegis.plugins")


class PluginManager:
    """Discovers and loads :class:`BasePlugin` implementations at runtime."""

    def __init__(self, plugins_dir: Path, registry: ToolRegistry) -> None:
        self.plugins_dir = plugins_dir.resolve()
        self.registry = registry
        self.loaded: list[BasePlugin] = []

    async def discover_and_load(self) -> list[BasePlugin]:
        """Asynchronously scan the plugin directory and load every plugin."""
        if not self.plugins_dir.is_dir():
            logger.warning("Plugin directory does not exist: %s", self.plugins_dir)
            return []

        files = await asyncio.to_thread(self._list_plugin_files)
        for file in files:
            try:
                await asyncio.to_thread(self._load_file, file)
            except Exception:  # noqa: BLE001 - a broken plugin must not stop boot
                logger.exception("Failed to load plugin file: %s", file.name)
        logger.info("Plugin manager loaded %d plugin(s): %s",
                    len(self.loaded), ", ".join(p.name for p in self.loaded) or "none")
        return self.loaded

    def _list_plugin_files(self) -> list[Path]:
        return sorted(
            p for p in self.plugins_dir.glob("*.py")
            if p.name not in {"__init__.py", "manager.py"}
        )

    def _load_file(self, file: Path) -> None:
        module_name = f"aegis_plugins.{file.stem}"
        spec = importlib.util.spec_from_file_location(module_name, file)
        if spec is None or spec.loader is None:
            logger.error("Could not create import spec for %s", file)
            return
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, BasePlugin) and obj is not BasePlugin and not inspect.isabstract(obj):
                if obj.__module__ != module_name:
                    continue  # skip imported base/other classes
                plugin = obj()
                plugin.register_tools(self.registry)
                self.loaded.append(plugin)
                logger.info("Loaded plugin '%s' v%s from %s", plugin.name, plugin.version, file.name)
