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
    return intent.strip().lower() in {"kg_lookup", "entity_lookup", "who", "what", "where"}

def describe_capabilities() -> str:
    return "Google Knowledge Graph lookup for entities/facts."

def handle(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not os.getenv("GOOGLE_API_KEY"):
        return {"status":"error","message":"GOOGLE_API_KEY missing"}
    q = (payload.get("query") or payload.get("text") or "").strip()
    if not q:
        return {"status":"error","message":"Missing query"}
    url = "https://kgsearch.googleapis.com/v1/entities:search?" + urlencode({
        "query": q, "key": os.getenv("GOOGLE_API_KEY"), "limit": 5, "languages": "en"
    })
    j = _http_json(url)
    items = j.get("itemListElement") or []
    results: List[dict] = []
    for it in items:
        e = it.get("result") or {}
        results.append({
            "name": e.get("name",""),
            "description": e.get("description",""),
            "detailedDescription": (e.get("detailedDescription") or {}).get("articleBody",""),
            "url": (e.get("detailedDescription") or {}).get("url",""),
            "score": it.get("resultScore", 0)
        })
    summary = "\n".join(f"- {r['name']}: {r['description']}" for r in results if r.get("name"))
    return {"status":"ok","results":results,"summary": summary or f"No KG facts for: {q}"}