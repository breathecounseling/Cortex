"""
executor/core/context_orchestrator.py
------------------------------------
Phase 2.18 — Context Orchestration with Design Prefs
"""

from __future__ import annotations
from typing import Dict, Any
from executor.utils.preference_graph import infer_palette_from_prefs, get_preferences

def gather_design_context(goal_text: str, session_id: str) -> Dict[str, Any]:
    """Collects design + preference cues for new builds (Echo → Prime)."""
    ui_prefs = {}
    try:
        palette = infer_palette_from_prefs()
        if palette: ui_prefs["palette"] = palette
    except Exception:
        ui_prefs["palette"] = "neutral"

    # shape/layout sentiment
    likes_ui = [p["item"] for p in get_preferences("ui", 0.0) if p["polarity"] > 0]
    ui_prefs["shape_pref"] = "rounded" if any("round" in s for s in likes_ui) else None

    # domain prefs (food etc.)
    domain_prefs = {}
    for dom in ("food", "color", "ui"):
        try:
            prefs = get_preferences(dom, 0.0)
            domain_prefs[dom] = {
                "likes": [p["item"] for p in prefs if p["polarity"] > 0],
                "dislikes": [p["item"] for p in prefs if p["polarity"] < 0],
            }
        except Exception:
            continue

    return {
        "goal": goal_text,
        "ui_prefs": ui_prefs,
        "domain_prefs": domain_prefs,
    }