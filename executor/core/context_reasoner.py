"""
executor/core/context_reasoner.py
---------------------------------
Phase 2.13d — Natural-language tone/personality assignment.
Echo now interprets sentences such as:
  "Be creative and imaginative."
  "Act like a business consultant."
  "Sound calm and thoughtful."
and updates session tone automatically.
"""

from __future__ import annotations
import re
from typing import Dict, Any
from executor.utils import memory_graph as gmem
from executor.utils.session_context import get_tone, set_tone
from executor.utils.personality_adapter import style_response


# --- Tone detection patterns ---
RX_TONE_DIRECT = re.compile(
    r"(?i)\b(?:be|act|sound|respond|talk)\s+(?:like|as|in\s+a)?\s*(?P<style>[a-z\s,]+)[.!]?$"
)
RX_TONE_TRAIT = re.compile(
    r"(?i)\b(?:be|act|sound|respond|talk)\s+(?P<traits>(?:\w+\s*,?\s*){1,5})"
)


def reason_about_context(intent: Dict[str, Any], query: str, session_id: str | None = None) -> Dict[str, Any]:
    """Performs contextual reasoning, now including tone/personality interpretation."""
    try:
        if not intent or not isinstance(intent, dict):
            return {"intent": "smalltalk", "reply": None}

        q = (query or "").strip()
        lower_q = q.lower()
        tone = get_tone(session_id) if session_id else "neutral"

        # --- Personality / tone assignment ---
        m = RX_TONE_DIRECT.search(lower_q) or RX_TONE_TRAIT.search(lower_q)
        if m:
            style = m.group("style") if "style" in m.groupdict() and m.group("style") else m.group("traits")
            style = style.strip().replace(",", " ").replace("  ", " ")
            if style:
                set_tone(session_id, style)
                msg = f"Got it — I'll respond in a {style} tone from now on."
                return {"intent": "tone.update", "reply": style_response(msg, style)}

        # --- Relational reasoning ---
        if re.search(r"\b(what\s+goes\s+with|pairs\s+with|complements)\b", lower_q):
            related = gmem.find_related_nodes(q)
            if not related:
                return {"intent": "relation.query",
                        "reply": style_response("I don't yet have associations for that.", tone)}
            unique = []
            for n in related:
                if n not in unique:
                    unique.append(n)
            joined = ", ".join(unique)
            base = f"{unique[0].capitalize()} goes well with {joined} because they complement each other in feel and purpose."
            return {"intent": "relation.query", "reply": style_response(base, tone)}

        # --- Default fallthrough ---
        return intent

    except Exception as e:
        print("[ContextReasonerError]", e)
        return {"intent": "error", "reply": f"(context failure) {e}"}


def build_context_block(query: str, session_id: str | None = None) -> str:
    """Builds a contextual system prompt for LLM fallback, preserving tone."""
    tone = get_tone(session_id) if session_id else "neutral"
    return f"Current query: {query.strip()}\nThe assistant speaks in a {tone} tone."