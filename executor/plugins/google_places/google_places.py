from __future__ import annotations
import os, json
from typing import Dict, Any, List
from urllib.parse import urlencode
from urllib.request import Request, urlopen

def _http_json(url: str, headers: dict | None = None) -> dict:
    req = Request(url, headers=headers or {"User-Agent": "CortexWeb/1.0"})
    with urlopen(req, timeout=12) as r:
        try:
            return json.loads(r.read().decode("utf-8", errors="ignore"))
        except Exception:
            return {}

def can_handle(intent: str) -> bool:
    return intent.strip().lower() in {"places_search","near_me","local_search"}

def describe_capabilities() -> str:
    return "Google Places & Geocoding based local search."

def _geocode(city: str, key: str) -> tuple[float|None,float|None]:
    url = "https://maps.googleapis.com/maps/api/geocode/json?" + urlencode({"address": city, "key": key})
    j = _http_json(url)
    try:
        loc = j["results"][0]["geometry"]["location"]
        return float(loc["lat"]), float(loc["lng"])
    except Exception:
        return None, None

def handle(payload: Dict[str, Any]) -> Dict[str, Any]:
    key = os.getenv("GOOGLE_API_KEY")
    if not key:
        return {"status":"error","message":"GOOGLE_API_KEY missing"}
    q = (payload.get("query") or payload.get("text") or "").strip()
    city = (payload.get("city") or "").strip()
    lat = payload.get("lat"); lon = payload.get("lon")

    if (lat is None or lon is None) and city:
        glat, glon = _geocode(city, key)
        if glat is not None and glon is not None:
            lat, lon = glat, glon

    if lat is None or lon is None:
        return {"status":"error","message":"Missing coordinates or city for local search"}

    url = "https://maps.googleapis.com/maps/api/place/textsearch/json?" + urlencode({
        "query": q or "coffee",
        "location": f"{lat},{lon}",
        "radius": 10000,
        "key": key
    })
    j = _http_json(url)
    results: List[dict] = []
    for r in (j.get("results") or [])[:8]:
        results.append({
            "name": r.get("name",""),
            "address": r.get("formatted_address",""),
            "rating": r.get("rating", None),
            "user_ratings_total": r.get("user_ratings_total", 0),
            "place_id": r.get("place_id","")
        })
    summary = "\n".join(
        f"- {r['name']} ({r.get('rating','?')}★, {r.get('user_ratings_total',0)} reviews) — {r['address']}"
        for r in results if r.get("name")
    )
    return {"status":"ok","results":results,"summary": summary or "No nearby places found."}