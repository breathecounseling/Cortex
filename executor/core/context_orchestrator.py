"""
executor/core/context_orchestrator.py
-------------------------------------
Collect a cross-domain DesignContext for a goal (UI prefs, domain prefs, related modules, signals).
2.11.2: surfaces UI likes/dislikes from preference graph alongside the ui_profile.
"""

from __future__ import annotations
from typing import Dict, List
from executor.utils.ui_profile import get_ui_profile
from executor.utils.preference_graph import get_preferences, get_dislikes
from executor.utils.turn_log import search_turns_keyword

def _related_modules_stub(goal: str) -> List[Dict]:
    mods = []
    g = (goal or "").lower()
    if "fitness" in g or "workout" in g:
        mods.append({"name": "calendar", "hooks": ["propose_time_slots"]})
    if "meal" in g or "recipe" in g or "planner" in g:
        mods.append({"name": "shopping_list", "hooks": ["merge_dislikes", "seed_cuisine"]})
    return mods

def gather_design_context(goal: str, session_id: str) -> Dict:
    # Base UI profile (graph + inferred palette)
    ui_profile = get_ui_profile()

    # UI likes/dislikes from preference graph
    ui_prefs  = get_preferences("ui", min_strength=0.0)
    ui_likes  = [p["item"] for p in ui_prefs if p["polarity"] > 0]
    ui_dislikes = [p["item"] for p in ui_prefs if p["polarity"] < 0]
    if ui_likes:
        ui_profile["likes"] = list(set(ui_likes))
    if ui_dislikes:
        ui_profile["dislikes"] = list(set(ui_dislikes))

    # Food preferences
    food_prefs  = get_preferences("food", min_strength=0.0)
    food_likes  = [p["item"] for p in food_prefs if p["polarity"] > 0]
    food_dislikes = [p["item"] for p in food_prefs if p["polarity"] < 0]

    # Signals from turn_log (cheap keyword pass)
    signals = []
    for kw in ["seafood","cajun","broccoli","oyster","oysters","gumbo","pizza","sushi","pasta","ramen"]:
        for hit in search_turns_keyword(kw, session_id=session_id, limit=5):
            signals.append({"source": "turn_log", "text": hit["text"], "kw": kw, "ts": hit["ts"]})

    related = _related_modules_stub(goal)

    return {
        "user_profile": {},  # reserved
        "ui_prefs": ui_profile,
        "domain_prefs": {
            "food": {"likes": list(set(food_likes)), "dislikes": list(set(food_dislikes))},
            "ui":   {"likes": ui_profile.get("likes", []), "dislikes": ui_profile.get("dislikes", [])},
        },
        "related_modules": related,
        "signals": signals,
        "constraints": [],
    }