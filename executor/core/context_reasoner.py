"""
executor/core/context_reasoner.py
---------------------------------
2.11.1 hotfix: minimal temporal recall handler + existing reasoning utilities.
"""

from __future__ import annotations
import re, json, time
from typing import Dict, Any, List
from executor.utils.turn_memory import get_recent_turns
from executor.utils.session_context import get_last_fact, set_topic, get_topic
from executor.utils.memory_graph import (
    detect_domain_from_key,
    contains_negation,
    extract_topic_intro,
)
from executor.utils.turn_log import search_turns_keyword

SHORT_REPLY_WORDS = 3
RECENT_QUERY_WINDOW = 3

def reason_about_context(intent: Dict[str, Any], text: str, session_id: str = "default") -> Dict[str, Any]:
    updated = intent.copy()
    last_dom, last_key = get_last_fact(session_id)

    # Topic intro
    topic = extract_topic_intro(text)
    if topic:
        print(f"[ContextReasoner] Topic intro detected: {topic}")
        set_topic(session_id, topic)
        updated["intent"] = "smalltalk"
        updated["domain"] = None
        updated["__reset_context"] = True
        return updated

    # --- Temporal recall hotfix ---
    if re.search(r"\b(earlier|today|yesterday|this (morning|afternoon|evening))\b", (text or "").lower()):
        hits = search_turns_keyword("", session_id=session_id, limit=10)
        if hits:
            # show last few distinct user entries
            recent = [h["text"] for h in hits[-5:]]
            updated["intent"] = "temporal.recall"
            updated["reply"] = "Here’s what we discussed recently: " + "; ".join(recent)
            return updated
        updated["intent"] = "temporal.recall"
        updated["reply"] = "I don't see anything new from earlier today."
        return updated

    # Negation handling (unchanged)
    if updated.get("intent") == "fact.update" and contains_negation(text):
        m = re.search(r"\bnot\s+([\w\s]+?)\s*(?:—|-|,|;|:)\s*(?P<alt>[\w\s]+)$", text.strip(), re.I)
        if last_dom and last_key and m and m.group("alt").strip():
            alt = m.group("alt").strip()
            print(f"[ContextReasoner] Negation replace: {last_key} -> {alt}")
            updated.update({"domain": last_dom, "key": last_key, "value": alt, "confidence": 0.95})
            return updated
        if last_dom and last_key:
            print(f"[ContextReasoner] Negation detected; clearing {last_key}")
            updated.update({"intent": "fact.delete", "domain": last_dom, "key": last_key, "value": None, "confidence": 0.95})
            return updated

    # Short-reply corrections (guarded)
    if updated.get("intent") in ("smalltalk", "other") and len((text or "").split()) <= SHORT_REPLY_WORDS:
        # (keep your existing recent-query logic here if present)
        pass

    # Confidence recovery (unchanged)
    if updated.get("confidence", 1.0) < 0.8 and updated.get("key"):
        dom_guess = updated.get("domain") or detect_domain_from_key(updated["key"])
        updated["domain"] = dom_guess
        updated["intent"] = "fact.query"
        updated["confidence"] = 0.9

    # Domain sanity check + topic bias (unchanged base)
    if updated.get("key"):
        detected = detect_domain_from_key(updated["key"])
        if updated.get("domain") and updated["domain"] != detected:
            updated["domain"] = detected
        topic = get_topic(session_id)
        if topic and (updated.get("domain") in (None, "misc", "favorite") or updated["domain"] == "current"):
            inferred = detect_domain_from_key(f"{topic} {updated['key']}")
            if inferred and inferred != updated["domain"]:
                print(f"[ContextReasoner] Topic-aware domain override: {inferred}")
                updated["domain"] = inferred

    return updated

def build_context_block(query: str, session_id: str = "default") -> str:
    from executor.utils.turn_memory import get_recent_context_text
    from executor.utils import memory_graph as gmem

    turn_text = get_recent_context_text(limit=10, session_id=session_id)
    try:
        facts = gmem.list_facts() if hasattr(gmem, "list_facts") else {}
        fact_text = json.dumps(facts)
    except Exception:
        fact_text = "{}"
    return (
        f"Recent conversation:\n{turn_text}\n\n"
        f"Known user facts: {fact_text}\n\n"
        f"Current query: {query.strip()}"
    )