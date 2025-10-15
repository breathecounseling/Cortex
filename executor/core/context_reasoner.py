"""
executor/core/context_reasoner.py
---------------------------------
Context Reasoner — short-term conversational reasoning for Echo.
Adds negation handling, topic switching, short-reply corrections,
and confidence recovery.
"""

from __future__ import annotations
import re, json
from typing import Dict, Any, Optional, List

from executor.utils.turn_memory import get_recent_turns
from executor.utils.session_context import get_last_fact
from executor.utils.memory_graph import (
    detect_domain_from_key,
    contains_negation,
    extract_topic_intro,
)

SHORT_REPLY_WORDS = 3
RECENT_QUERY_WINDOW = 3   # require recent fact query
SMALLTALK_COOLDOWN = 5    # after 5 neutral turns, reset continuity


def reason_about_context(intent: Dict[str, Any], text: str, session_id: str = "default") -> Dict[str, Any]:
    updated = intent.copy()
    turns = get_recent_turns(session_id=session_id)
    last_dom, last_key = get_last_fact(session_id)

    # --- 1️⃣  Topic intro: reset continuity
    topic = extract_topic_intro(text)
    if topic:
        print(f"[ContextReasoner] Topic intro detected: {topic}")
        updated["intent"] = "smalltalk"
        updated["domain"] = None
        updated["__reset_context"] = True
        return updated

    # --- 2️⃣  Negation handling
    if updated.get("intent") == "fact.update" and contains_negation(text):
        m = re.search(r"\bnot\b[^A-Za-z0-9]+(?P<alt>[\w\s]+)$", text.strip(), re.I)
        if last_dom and last_key and m and m.group("alt").strip():
            alt = m.group("alt").strip()
            print(f"[ContextReasoner] Negation replace: {last_key} -> {alt}")
            updated.update({
                "domain": last_dom,
                "key": last_key,
                "value": alt,
                "confidence": 0.95
            })
            return updated
        if last_dom and last_key:
            print(f"[ContextReasoner] Negation detected; clearing {last_key}")
            updated.update({
                "intent": "fact.delete",
                "domain": last_dom,
                "key": last_key,
                "value": None,
                "confidence": 0.95
            })
            return updated

    # --- 3️⃣  Short-reply correction
    if updated.get("intent") in ("smalltalk", "other") and len(text.split()) <= SHORT_REPLY_WORDS:
        recent_user_texts = [t["content"].lower() for t in turns[-RECENT_QUERY_WINDOW:] if t["role"] == "user"]
        asked_fact = any(("what's my" in u or "what is my" in u) for u in recent_user_texts)
        asked_home = any("where do i live" in u for u in recent_user_texts)
        asked_current = any(("where am i" in u or "current location" in u) for u in recent_user_texts)

        if (asked_fact or asked_home or asked_current) and last_key:
            if asked_fact:
                domain = detect_domain_from_key(last_key)
                updated.update({
                    "intent": "fact.update",
                    "domain": domain,
                    "key": last_key,
                    "value": text.strip(" .!?"),
                    "confidence": 0.95
                })
            else:
                scope = "home" if asked_home else "current"
                updated.update({
                    "intent": "location.update",
                    "domain": "location",
                    "key": scope,
                    "scope": scope,
                    "value": text.strip(" .!?"),
                    "confidence": 0.95
                })
            print(f"[ContextReasoner] Short reply reclassified for {updated['domain']}.{updated['key']}")
            return updated

    # --- 4️⃣  Confidence recovery
    if updated.get("confidence", 1.0) < 0.8 and updated.get("key"):
        dom_guess = updated.get("domain") or detect_domain_from_key(updated["key"])
        updated["domain"] = dom_guess
        updated["intent"] = "fact.query"
        updated["confidence"] = 0.9

    # --- 5️⃣  Domain sanity check
    if updated.get("key"):
        detected = detect_domain_from_key(updated["key"])
        if updated.get("domain") and updated["domain"] != detected:
            updated["domain"] = detected

    return updated


def build_context_block(query: str, session_id: str = "default") -> str:
    from executor.utils.turn_memory import get_recent_context_text
    from executor.utils import memory_graph as gmem

    turn_text = get_recent_context_text(limit=10, session_id=session_id)
    try:
        facts = gmem.list_facts()
        fact_text = json.dumps(facts)
    except Exception:
        fact_text = "{}"
    return (
        f"Recent conversation:\n{turn_text}\n\n"
        f"Known user facts: {fact_text}\n\n"
        f"Current query: {query.strip()}"
    )