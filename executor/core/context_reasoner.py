"""
executor/core/context_reasoner.py
---------------------------------
Phase 2.13 — Relational reasoning cleanup + tone integration.
"""

from __future__ import annotations
from typing import Dict, Any, List
import re
from executor.utils import memory_graph as gmem
from executor.utils.session_context import get_tone
from executor.utils.personality_adapter import style_response


def reason_about_context(intent: Dict[str, Any], query: str, session_id: str | None = None) -> Dict[str, Any]:
    """
    Performs contextual reasoning based on the parsed intent and session state.
    Now uses tone-aware output styling.
    """
    try:
        if not intent or not isinstance(intent, dict):
            return {"intent": "smalltalk", "reply": None}

        q = (query or "").lower().strip()
        tone = get_tone(session_id) if session_id else "neutral"

        # --- Handle relational lookups like "what goes with cozy layouts"
        if re.search(r"\b(what\s+goes\s+with|pairs\s+with|complements)\b", q):
            node = gmem.find_related_nodes(q)
            if not node:
                return {"intent": "relation.query", "reply": style_response("I don't yet have associations for that.", tone)}

            # Deduplicate results + format cleanly
            unique = []
            for n in node:
                if n not in unique:
                    unique.append(n)

            joined = ", ".join(unique)
            base = f"{unique[0].capitalize()} goes well with {joined} because they complement each other in feel and purpose."
            return {"intent": "relation.query", "reply": style_response(base, tone)}

        # --- Reflective questions or temporal recall are handled upstream ---
        return intent
    except Exception as e:
        print("[ContextReasonerError]", e)
        return {"intent": "error", "reply": f"(context failure) {e}"}


def build_context_block(query: str, session_id: str | None = None) -> str:
    """
    Builds a contextual system prompt for LLM fallback.
    Includes personality tone for stylistic continuity.
    """
    tone = get_tone(session_id) if session_id else "neutral"
    tone_hint = f"The assistant speaks in a {tone} tone."
    return f"Current query: {query.strip()}\n{tone_hint}"