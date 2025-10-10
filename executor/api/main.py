from __future__ import annotations

"""
Cortex API Server
-----------------
FastAPI entrypoint for chat and execution requests.
Routes user input through the router, dispatcher, and plugin registry.

Phase 2.5 update:
- Adds explicit plugin handlers for weather_plugin, google_kg, google_places, and web_search.
- Safe fallbacks if any plugin raises or returns error.
"""

import os
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict

from executor.core.router import route
from executor.plugins.web_search import web_search
from executor.plugins.weather_plugin import weather_plugin
from executor.plugins.google_kg import google_kg
from executor.plugins.google_places import google_places
from executor.plugins.feedback import feedback

app = FastAPI()


# ---------- Models ----------
class ChatBody(BaseModel):
    text: str
    boost: bool | None = False
    system: str | None = None


# ---------- Health ----------
@app.get("/")
def root() -> Dict[str, Any]:
    return {"status": "ok", "message": "Cortex API is running."}


# ---------- Main chat endpoint ----------
@app.post("/chat")
def chat(body: ChatBody) -> Dict[str, Any]:
    """Primary chat interface for UI."""
    text = (body.text or "").strip()
    if not text:
        return {"reply": "How can I help?"}

    try:
        router_output = route(text)
    except Exception as e:
        return {"reply": f"Router error: {e}"}

    # If router produced no actions, return default assistant message
    if not router_output.get("actions"):
        return {"reply": router_output.get("assistant_message", "Okay.")}

    # Process the first action only (single-task flow)
    action = router_output["actions"][0]
    plugin = action.get("plugin")
    args = action.get("args", {})

    # -------- Plugin handlers --------
    try:
        # 🌐 Web Search
        if plugin == "web_search":
            result = web_search.handle(args)
            if result.get("status") == "ok":
                return {"reply": result.get("summary", "No search results.")}
            return {"reply": result.get("message", "Search failed.")}

        # 🌦 Weather Plugin
        elif plugin == "weather_plugin":
            result = weather_plugin.handle(args)
            if result.get("status") == "ok":
                return {"reply": result.get("summary", "No weather data.")}
            return {"reply": result.get("message", "Weather lookup failed.")}

        # 🧭 Google Places
        elif plugin == "google_places":
            result = google_places.handle(args)
            if result.get("status") == "ok":
                return {"reply": result.get("summary", "No nearby places found.")}
            return {"reply": result.get("message", "Places lookup failed.")}

        # 🧠 Google Knowledge Graph
        elif plugin == "google_kg":
            result = google_kg.handle(args)
            if result.get("status") == "ok":
                return {"reply": result.get("summary", "No entity data found.")}
            return {"reply": result.get("message", "KG lookup failed.")}

        # 🗳 Feedback plugin (if triggered manually)
        elif plugin == "feedback":
            result = feedback.handle(args)
            return {"reply": result.get("message", "Feedback noted.")}

        # Default fallback: echo assistant_message
        else:
            return {"reply": router_output.get("assistant_message", "Okay.")}

    except Exception as e:
        return {"reply": f"Plugin error ({plugin}): {e}"}


# ---------- /execute endpoint (optional) ----------
@app.post("/execute")
def execute(body: Dict[str, Any]) -> Dict[str, Any]:
    """Execute direct plugin or command payloads (used by internal agents)."""
    plugin = body.get("plugin")
    args = body.get("args", {})
    if not plugin:
        return {"status": "error", "message": "Missing plugin name."}

    try:
        if plugin == "web_search":
            return web_search.handle(args)
        if plugin == "weather_plugin":
            return weather_plugin.handle(args)
        if plugin == "google_places":
            return google_places.handle(args)
        if plugin == "google_kg":
            return google_kg.handle(args)
        if plugin == "feedback":
            return feedback.handle(args)
    except Exception as e:
        return {"status": "error", "message": f"{plugin} failed: {e}"}

    return {"status": "error", "message": f"Unknown plugin: {plugin}"}


# ---------- Startup message ----------
@app.on_event("startup")
def startup_message() -> None:
    print("✅ Cortex API started — ready for chat and plugin actions.")