"""
executor/core/context_orchestrator.py
-------------------------------------
Collect a cross-domain DesignContext for a goal (UI prefs, domain prefs, related modules, signals).
"""

from __future__ import annotations
from typing import Dict, List
from executor.utils.ui_profile import get_ui_profile
from executor.utils.preference_graph import get_preferences, get_dislikes
from executor.utils.turn_log import search_turns_keyword, search_turns_semantic
from executor.utils.signal_harvesters import harvest_food_signals, harvest_ui_signals

def _related_modules_stub(goal: str) -> List[Dict]:
    # Minimal related-modules stub; later tie into plugin registry
    mods = []
    g = (goal or "").lower()
    if "fitness" in g or "workout" in g:
        mods.append({"name": "calendar", "hooks": ["propose_time_slots"]})
    if "meal" in g or "planner" in g:
        mods.append({"name": "shopping_list", "hooks": ["merge_dislikes", "seed_cuisine"]})
    return mods

def gather_design_context(goal: str, session_id: str) -> Dict:
    ui = get_ui_profile()
    # Ensure food signals harvested once in a while (cheap)
    harvest_food_signals(session_id=session_id, limit=300)
    harvest_ui_signals(session_id=session_id, limit=300)

    food_likes = [p["item"] for p in get_preferences("food", min_strength=0.0) if p["polarity"] > 0]
    food_dislikes = [d["item"] for d in get_dislikes("food")]

    signals = []
    for kw in ["seafood", "cajun", "broccoli", "rounded", "earth tones", "palette"]:
        for hit in search_turns_keyword(kw, session_id=session_id, limit=10):
            signals.append({"source": "turn_log", "text": hit["text"], "kw": kw, "ts": hit["ts"]})

    related = _related_modules_stub(goal)
    return {
        "user_profile": {},  # placeholder for future user_profile facts
        "ui_prefs": ui,
        "domain_prefs": {
            "food": {"likes": list(set(food_likes)), "dislikes": list(set(food_dislikes))}
        },
        "related_modules": related,
        "signals": signals,
        "constraints": [],
    }