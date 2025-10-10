from __future__ import annotations
import os, json, re, html
from typing import Dict, Any, List, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from executor.utils.web_cache import get as cache_get, put as cache_put

# ---------- Provider selection ----------
def _choose_provider() -> str:
    if os.getenv("GOOGLE_API_KEY") and os.getenv("GOOGLE_CX"):
        return "google"
    if os.getenv("SEARCH_API_KEY"):  # Bing
        return "bing"
    return "ddg"

# ---------- HTTP helpers (stdlib, no extra deps) ----------
def _http_json(url: str, headers: Dict[str, str] | None = None) -> dict:
    req = Request(url, headers=headers or {"User-Agent": "CortexWeb/1.0"})
    with urlopen(req, timeout=15) as r:
        data = r.read().decode("utf-8", errors="ignore")
        try:
            return json.loads(data)
        except Exception:
            return {"raw": data}

def _http_text(url: str, headers: Dict[str, str] | None = None) -> str:
    req = Request(url, headers=headers or {"User-Agent": "CortexWeb/1.0"})
    with urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", errors="ignore")

# ---------- Providers ----------
def _google_search(q: str) -> Tuple[str, List[dict]]:
    key = os.getenv("GOOGLE_API_KEY"); cx = os.getenv("GOOGLE_CX")
    url = f"https://www.googleapis.com/customsearch/v1?{urlencode({'key': key, 'cx': cx, 'q': q})}"
    j = _http_json(url)
    items = j.get("items") or []
    results = [{"title": i.get("title",""), "url": i.get("link",""), "snippet": i.get("snippet","")} for i in items[:5]]
    return "google", results

def _bing_search(q: str) -> Tuple[str, List[dict]]:
    key = os.getenv("SEARCH_API_KEY")
    url = f"https://api.bing.microsoft.com/v7.0/search?{urlencode({'q': q, 'mkt': 'en-US'})}"
    j = _http_json(url, headers={"Ocp-Apim-Subscription-Key": key})
    web = (j.get("webPages") or {}).get("value") or []
    results = [{"title": i.get("name",""), "url": i.get("url",""), "snippet": i.get("snippet","")} for i in web[:5]]
    return "bing", results

def _ddg_search(q: str) -> Tuple[str, List[dict]]:
    # Use the HTML results page and extract a few top links by regex (lightweight fallback).
    html_text = _http_text(f"https://html.duckduckgo.com/html/?{urlencode({'q': q})}",
                           headers={"User-Agent": "CortexWeb/1.0", "Accept-Language": "en-US,en"})
    # crude extraction (keep simple, resilient to minor changes)
    links = re.findall(r'<a rel="nofollow" class="result__a" href="([^"]+)".*?>(.*?)</a>', html_text, flags=re.S)
    snippets = re.findall(r'<a.*?result__snippet.*?>(.*?)</a>', html_text, flags=re.S)
    results = []
    for idx, (u, t) in enumerate(links[:5]):
        title = html.unescape(re.sub(r"<.*?>", "", t)).strip()
        url = html.unescape(u).strip()
        snip = html.unescape(re.sub(r"<.*?>", "", snippets[idx] if idx < len(snippets) else "")).strip()
        results.append({"title": title, "url": url, "snippet": snip})
    return "ddg", results

# ---------- Summarization (optional; degrade gracefully) ----------
def _summarize(query: str, results: List[dict]) -> str:
    if not results:
        return f"No results for: {query}"
    # If an LLM is available, you may wire to your summarizer here.
    bullets = []
    for r in results:
        title = r.get("title","").strip()[:140]
        snippet = r.get("snippet","").strip()
        url = r.get("url","")
        bullets.append(f"- {title} — {snippet} ({url})")
    return f"Top findings for “{query}”:\n" + "\n".join(bullets)

# ---------- Plugin interface ----------
def can_handle(intent: str) -> bool:
    return intent.lower().strip() in {"web_search", "search", "lookup", "weather", "news"}

def describe_capabilities() -> str:
    return "Live web search with provider auto-detect (Google→Bing→DuckDuckGo) + caching."

def handle(payload: Dict[str, Any]) -> Dict[str, Any]:
    query = (payload.get("query") or payload.get("text") or "").strip()
    if not query:
        return {"status": "error", "message": "Missing 'query' for web_search."}

    # Check cache first
    cached = cache_get(query)
    if cached:
        provider, data = cached
        return {"status": "ok", "provider": provider, "results": data.get("results", []),
                "summary": data.get("summary", ""), "cached": True}

    # Choose provider
    provider = _choose_provider()
    try:
        if provider == "google":
            p, results = _google_search(query)
        elif provider == "bing":
            p, results = _bing_search(query)
        else:
            p, results = _ddg_search(query)
    except Exception as e:
        return {"status": "error", "message": f"Search failed: {e}"}

    summary = _summarize(query, results)
    payload = {"results": results, "summary": summary}
    cache_put(query, p, payload)
    return {"status": "ok", "provider": p, **payload, "cached": False}