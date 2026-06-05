"""Sample plugin: a current-weather lookup tool.

This is a fully working reference implementation that demonstrates how to build
an Aegis-X plugin.  It exposes a single ``get_weather`` tool backed by the free,
key-less Open-Meteo API (geocoding + current forecast).
"""

from __future__ import annotations

from typing import Any

from tools.base import BasePlugin, BaseTool, ToolResult
from tools.registry import ToolRegistry

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


class GetWeatherTool(BaseTool):
    name = "get_weather"
    description = "Return the current temperature and wind for a given city name."
    parameters = {"city": "The name of the city to look up (e.g. 'Berlin')."}

    async def execute(self, **kwargs: Any) -> ToolResult:
        import httpx

        city = str(kwargs["city"]).strip()
        if not city:
            return ToolResult(success=False, error="Parameter 'city' must not be empty.", exit_code=2)

        async with httpx.AsyncClient(timeout=20) as client:
            geo = await client.get(_GEOCODE_URL, params={"name": city, "count": 1})
            geo.raise_for_status()
            results = geo.json().get("results") or []
            if not results:
                return ToolResult(success=False, error=f"City not found: {city}", exit_code=1)

            place = results[0]
            forecast = await client.get(
                _FORECAST_URL,
                params={
                    "latitude": place["latitude"],
                    "longitude": place["longitude"],
                    "current": "temperature_2m,wind_speed_10m",
                },
            )
            forecast.raise_for_status()
            current = forecast.json().get("current", {})

        summary = (
            f"Weather in {place['name']}, {place.get('country', '?')}: "
            f"{current.get('temperature_2m', '?')}°C, "
            f"wind {current.get('wind_speed_10m', '?')} km/h."
        )
        return ToolResult(success=True, output=summary, metadata={"location": place, "current": current})


class WeatherPlugin(BasePlugin):
    name = "weather"
    description = "Provides a current-weather lookup tool via the Open-Meteo API."
    version = "1.0.0"

    def register_tools(self, registry: ToolRegistry) -> None:
        registry.register(GetWeatherTool())
