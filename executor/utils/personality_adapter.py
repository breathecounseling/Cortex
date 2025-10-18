"""
executor/utils/personality_adapter.py
-------------------------------------
Phase 2.19 — tone styling with optional session awareness
"""

from __future__ import annotations
import random
from typing import Optional
from executor.utils.session_context import get_tone

def _trim(s: str) -> str:
    return " ".join((s or "").strip().split())

def style_response(text: str, tone: Optional[str] = None, session_id: Optional[str] = None) -> str:
    msg = _trim(text or "")
    if not msg: return msg

    # Session-aware fallback
    t = (tone or (get_tone(session_id) if session_id else "neutral") or "neutral").lower()

    if t in ("neutral", ""):
        return msg

    if "playful" in t or "creative" in t or "imaginative" in t:
        spice = ["✨", "🌈", "🎨", "🦄", "💫"]
        tails = ["What a fun thought!", "Let’s make it magical!", "Love this direction!"]
        return _trim(f"{random.choice(spice)} {msg} {random.choice(spice)} {random.choice(tails)}")

    if "tough" in t or "coach" in t or "motivating" in t:
        tails = ["Let’s crush it.", "You’ve got this.", "No excuses — just action."]
        return _trim(f"{msg} 💪 {random.choice(tails)}")

    if "calm" in t or "thoughtful" in t or "reflective" in t:
        return _trim(f"{msg} ☕ Take a breath and we’ll move step by step.")

    if "strategic" in t or "focused" in t or "business" in t:
        return _trim(f"{msg} 📊 Let’s proceed with clarity and purpose.")

    if "friendly" in t or "compassionate" in t or "gentle" in t:
        return _trim(f"{msg} 💛 I’m with you.")

    if "whimsical" in t or "poetic" in t:
        return _trim(f"🌙 {msg.capitalize()} — steady as moonlight. 🌸")

    return msg