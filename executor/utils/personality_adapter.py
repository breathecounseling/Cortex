"""
executor/utils/personality_adapter.py
-------------------------------------
Applies conversational style and personality tone to responses.
Learns and adjusts tone dynamically based on user feedback or repeated cues.

Phase 2.12c — Adaptive personality memory
Integrates with domain-based tone inheritance and reasoning layers.
"""

import random
from executor.utils.session_context import get_tone, set_tone


def _merge_tones(current: str, new: str) -> str:
    """
    Merge tone descriptors naturally (e.g. calm + reflective -> calm and reflective).
    """
    if not current or current.lower() == "neutral":
        return new
    if new.lower() in current.lower():
        return current  # already known
    # Avoid duplicates and overly long tone strings
    merged = f"{current}, {new}".strip(", ")
    if len(merged.split()) > 6:
        merged = new  # reset if getting verbose
    return merged


def learn_tone(session_id: str, cue: str) -> str:
    """
    When user gives a tone directive like "be gentle" or "be motivating",
    this function updates and persists the tone.
    """
    new_tone = cue.lower().replace("be ", "").strip()
    current = get_tone(session_id)
    merged = _merge_tones(current, new_tone)
    set_tone(session_id, merged)
    print(f"[ToneLearning] Updated tone for session {session_id}: {merged}")
    return merged


def style_response(text: str, tone: str = "neutral", session_id: str | None = None) -> str:
    """Apply a linguistic style based on tone archetype."""
    t = (tone or get_tone(session_id) or "neutral").lower().strip()
    if t in ("neutral", "", None):
        return text

    # --- Creative / Playful ---
    if "playful" in t or "creative" in t or "imaginative" in t:
        extras = [
            "✨", "🌈", "🎨", "🦄", "💫",
            "What a fun thought!", "Let’s make it magical!",
            "Ooh, I love where this is going!"
        ]
        return f"{random.choice(extras)} {text.capitalize()} {random.choice(extras)}"

    # --- Motivating / Tough ---
    if "motivating" in t or "tough" in t or "coach" in t:
        extras = [
            "Let’s crush it.", "You’ve got this.",
            "No excuses—just action.", "Dig deep and push harder."
        ]
        return f"{text} 💪 {random.choice(extras)}"

    # --- Calm / Reflective ---
    if "calm" in t or "thoughtful" in t or "reflective" in t:
        return f"{text} ☕ Take a moment to breathe and reflect."

    # --- Focused / Strategic ---
    if "focused" in t or "strategic" in t or "business" in t:
        return f"{text} 📊 Let’s move with clarity and purpose."

    # --- Friendly / Supportive ---
    if "friendly" in t or "compassionate" in t or "gentle" in t:
        return f"{text} 💛 I’m here with you."

    # --- Whimsical / Poetic ---
    if "whimsical" in t or "poetic" in t:
        return f"🌙 {text.capitalize()} — like a soft echo in twilight. 🌸"

    # --- Fallback ---
    return f"{text} ({tone})"