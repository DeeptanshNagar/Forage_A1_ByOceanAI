"""Keyless public HTTP API tool (Open-Meteo geocoding + current weather) with a strict host allowlist and timeouts."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from .registry import Tool

ALLOWED_HOSTS = {"api.open-meteo.com", "geocoding-api.open-meteo.com"}
TIMEOUT_S = 10.0


class HostNotAllowed(PermissionError):
    pass


def safe_get(url: str, params: dict[str, Any]) -> dict[str, Any]:
    host = urlparse(url).hostname or ""
    if urlparse(url).scheme != "https" or host not in ALLOWED_HOSTS:
        raise HostNotAllowed(f"host '{host}' is not in the allowlist")
    r = httpx.get(url, params=params, timeout=TIMEOUT_S, follow_redirects=False)
    r.raise_for_status()
    return r.json()


def weather(args: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    lat, lon = args.get("latitude"), args.get("longitude")
    place = args.get("city") or args.get("location") or args.get("query")
    if (lat is None or lon is None) and place:
        g = safe_get("https://geocoding-api.open-meteo.com/v1/search", {"name": str(place)[:80], "count": 1})
        if not g.get("results"):
            return {"error": f"location '{place}' not found"}
        lat, lon = g["results"][0]["latitude"], g["results"][0]["longitude"]
        place = g["results"][0].get("name", place)
    if lat is None or lon is None:
        raise ValueError("provide 'city' or 'latitude' and 'longitude'")
    w = safe_get("https://api.open-meteo.com/v1/forecast",
                 {"latitude": float(lat), "longitude": float(lon), "current_weather": "true"})
    return {"location": place, "latitude": lat, "longitude": lon, "current_weather": w.get("current_weather", {})}


TOOL = Tool(
    name="http_api",
    description="Fetch live current weather for a city or coordinates from the public Open-Meteo API (internet access).",
    capability_tags=["live_weather", "geocoding", "internet_api"],
    input_schema={"type": "object", "properties": {"city": {"type": "string"}, "latitude": {"type": "number"},
                                                   "longitude": {"type": "number"}}},
    func=weather,
    requires_network=True,
)
