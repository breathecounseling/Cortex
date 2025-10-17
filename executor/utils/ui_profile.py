"""
executor/utils/ui_profile.py
----------------------------
Cross-module UI preferences: palette, shapes, density, charts, fonts.
Reads from graph_nodes where possible; falls back to preference_graph inference.
"""

from __future__ import annotations
from typing import Dict, Optional
from executor.utils import memory_graph as gmem
from executor.utils.preference_graph import infer_palette_from_prefs

def _node(domain: str, key: str, scope: str = "global") -> Optional[str]:
    n = gmem.get_node(domain, key, scope=scope)
    return n["value"] if n and n.get("value") else None

def get_ui_profile() -> Dict:
    palette = _node("ui", "color_palette") or infer_palette_from_prefs().get("palette")
    shape   = _node("ui", "shape_pref") or "rounded"
    density = _node("ui", "density") or "cozy"
    charts  = _node("ui", "chart_pref") or "cards+donuts"
    font    = _node("ui", "font_pref") or "system"
    colors  = infer_palette_from_prefs().get("colors")
    return {
        "palette": palette,
        "colors": colors,
        "shape_pref": shape,
        "density": density,
        "chart_pref": charts,
        "font_pref": font,
    }