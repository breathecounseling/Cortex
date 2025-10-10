from __future__ import annotations
import json
from typing import Dict, Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

def _http_json(url: str, headers: dict | None = None) -> dict:
    req = Request(url, headers=headers or {"User-Agent":"CortexWeather/1.0"})
    with urlopen(req, timeout=12) as r:
        try:
            return json.loads(r.read().decode("utf-8", errors="ignore"))
        except Exception:
            return {}

def _geocode(city: str) -> tuple[float|None,float|None]:
    url = "https://nominatim.openstreetmap.org/search?" + urlencode({"q": city, "format": "json", "limit": 1})
    j = _http_json(url, headers={"User-Agent":"CortexWeather/1.0"})
    try:
        lat = float(j[0]["lat"]); lon = float(j[0]["lon"])
        return lat, lon
    except Exception:
        return None, None

def can_handle(intent: str) -> bool:
    return intent.strip().lower() in {"weather","forecast","weather_now"}

def describe_capabilities() -> str:
    return "Live weather via Open-Meteo; optional geocoding via Nominatim."

def handle(payload: Dict[str, Any]) -> Dict[str, Any]:
    city = (payload.get("city") or payload.get("query") or "").strip()
    lat = payload.get("lat"); lon = payload.get("lon")

    if (lat is None or lon is None) and city:
        glat, glon = _geocode(city)
        if glat is not None and glon is not None:
            lat, lon = glat, glon

    if lat is None or lon is None:
        return {"status":"error","message":"Provide city or coords for weather lookup."}

    url = "https://api.open-meteo.com/v1/forecast?" + urlencode({
        "latitude": lat, "longitude": lon, "current_weather": "true", "hourly": "temperature_2m,precipitation"
    })
    j = _http_json(url)
    cw = j.get("current_weather") or {}
    if not cw:
        return {"status":"error","message":"No weather data"}
    temp = cw.get("temperature","?"); wind = cw.get("windspeed","?")
    summary = f"Current weather: {temp}°C, wind {wind} km/h."
    return {"status":"ok","summary":summary,"data":j}