"""
executor/utils/signal_harvesters.py
-----------------------------------
Harvest structured signals (food, UI) from historical turn logs and write to preferences.
"""

from __future__ import annotations
import re
from typing import Dict, List
from executor.utils.turn_log import search_turns_keyword
from executor.utils.preference_graph import record_preference

FOOD_LIKE_RX = re.compile(r"(?i)\b(love|like|enjoy|crave|am\s+into)\b.*\b(seafood|cajun|sushi|pizza|pasta|korean|thai|indian)\b")
FOOD_DISLIKE_RX = re.compile(r"(?i)\b(don'?t\s+like|hate|can'?t\s+stand|avoid)\b.*\b(broccoli|liver|cilantro|brussels?)\b")

UI_TONE_RX = re.compile(r"(?i)\b(earth\s+tones|deep\s+earth\s+tones|dark\s+theme|light\s+theme)\b")
UI_SHAPE_RX = re.compile(r"(?i)\b(rounded|rounded\s+corners|square|squared)\b")

def harvest_food_signals(session_id: str | None = None, limit: int = 500) -> Dict:
    hits = search_turns_keyword("", session_id=session_id, limit=limit)
    likes, dislikes = [], []
    for h in hits:
        txt = h["text"]
        m1 = FOOD_LIKE_RX.search(txt)
        if m1:
            item = m1.group(2).lower()
            record_preference("food", item, polarity=+1, strength=0.8, source="turn_log")
            likes.append(item)
        m2 = FOOD_DISLIKE_RX.search(txt)
        if m2:
            item = m2.group(2).lower()
            record_preference("food", item, polarity=-1, strength=0.8, source="turn_log")
            dislikes.append(item)
    return {"likes": list(set(likes)), "dislikes": list(set(dislikes))}

def harvest_ui_signals(session_id: str | None = None, limit: int = 500) -> Dict:
    hits = search_turns_keyword("", session_id=session_id, limit=limit)
    tones, shapes = [], []
    for h in hits:
        txt = h["text"]
        m1 = UI_TONE_RX.search(txt)
        if m1:
            tones.append(m1.group(1).lower())
        m2 = UI_SHAPE_RX.search(txt)
        if m2:
            shapes.append(m2.group(1).lower())
    # Record derived preferences (soft)
    if any("earth" in t for t in tones):
        record_preference("color", "earth_tones", polarity=+1, strength=0.75, source="turn_log", cluster="rich_earth_tones")
    if any("rounded" in s for s in shapes):
        record_preference("ui", "rounded", polarity=+1, strength=0.75, source="turn_log")
    return {"tones": list(set(tones)), "shapes": list(set(shapes))}