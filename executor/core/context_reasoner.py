"""
executor/core/context_reasoner.py
---------------------------------
Phase 2.12c — Adaptive personality & tone learning

Adds:
- Integration with personality_adapter.learn_tone()
- Automatically detects tone cues from user input (e.g. "be calm", "be tough")
- Full persistence via session_context (tone column)
"""

from __future__ import annotations
import re
from typing import Dict, Any, Optional

from executor.utils import memory_graph as gmem
from executor.utils.session_context import (
    get_last_fact, set_last_fact,
    get_topic, set_topic,
    get_tone, set_tone,
)
from executor.utils.turn_memory import get_recent_turns
from executor.utils.personality_adapter import style_response, learn_tone
from executor.utils.domain_traits import get_domain_tone


# ---------- Core Reasoning ----------
def reason_about_context(intent: Dict[str, Any], query: str,
                         session_id: Optional[str] = None) -> Dict[str, Any]:
    """Interpret parsed intent with awareness of session, tone, and topic."""
    try:
        q = (query or "").strip().lower()
        topic = get_topic(session_id)
        tone = get_tone(session_id) if session_id else "neutral"
        last_dom, last_key = get_last_fact(session_id)

        # --- Detect explicit tone directives like "be calm", "be creative" ---
        m_tone = re.search(r"(?i)\b(?:be|sound|act|respond|talk)\s+(?:more\s+)?([\w\s]+)$", q)
        if m_tone:
            new_tone = m_tone.group(1).strip(" .!?")
            tone = learn_tone(session_id, new_tone)
            intent["intent"] = "tone.update"
            intent["reply"] = style_response(f"Okay — I'll be {new_tone} from now on.", tone=tone)
            return intent

        # --- Domain tone inheritance ---
        domain = intent.get("domain")
        if domain:
            tone_pref = get_domain_tone(domain)
            if tone_pref and tone_pref != "neutral":
                print(f"[ToneAdapt] Switching to domain tone: {tone_pref} ({domain})")
                set_tone(session_id, tone_pref)
                tone = tone_pref

        # --- Negation inference ---
        if re.match(r"(?i)\bno\b|not\b|none\b|never\b", q):
            intent["intent"] = "fact.delete"
            intent["reply"] = "Okay — I’ve cleared that for you."
            return intent

        # --- Temporal recall intent ---
        if re.search(r"\b(what did i say|remind me what we talked)\b", q):
            turns = get_recent_turns(session_id=session_id, limit=8)
            summary = "; ".join([t["content"] for t in turns if t["role"] == "user"])
            intent["intent"] = "temporal.recall"
            intent["reply"] = (
                f"Here’s what we discussed recently: {summary}"
                if summary else "I don’t have any recent conversation to recall."
            )
            return intent

        # --- Tone self-awareness ---
        if re.search(r"\bhow would you describe your tone\b", q):
            tone_now = get_tone(session_id) or "neutral"
            intent["intent"] = "meta.query"
            intent["reply"] = style_response(
                f"I would describe my tone as {tone_now}.",
                tone=tone_now
            )
            return intent

        # --- Contextual smalltalk fallback ---
        if intent.get("intent") == "smalltalk":
            reply = style_response("I'm here with you.", tone=tone)
            intent["reply"] = reply
            return intent

        # --- Fact correction & follow-through ---
        if intent.get("intent") == "fact.update" and not intent.get("domain"):
            if last_dom:
                intent["domain"] = last_dom
            if last_key and not intent.get("key"):
                intent["key"] = last_key

        # --- Topic memory integration ---
        if "topic" in q and not topic and last_dom:
            set_topic(session_id, last_dom)

        intent["tone"] = tone
        return intent

    except Exception as e:
        print("[ContextReasonerError]", e)
        intent["intent"] = "error"
        intent["reply"] = f"(internal reasoning error: {e})"
        return intent


# ---------- Context Builder ----------
def build_context_block(query: str, session_id: Optional[str] = None) -> str:
    """Construct a synthetic prompt for the reasoning model."""
    topic = get_topic(session_id)
    tone = get_tone(session_id) if session_id else "neutral"
    turns = get_recent_turns(session_id=session_id, limit=6)
    recent_dialogue = "\n".join(
        [f"{t['role']}: {t['content']}" for t in turns]
    )

    context_parts = [
        f"Active tone: {tone}.",
        f"Current topic: {topic or 'general conversation'}.",
        f"Recent dialogue:\n{recent_dialogue}",
        f"Current query: {query.strip()}",
    ]
    return "\n".join(context_parts)