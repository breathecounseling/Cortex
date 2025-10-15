# executor/core/context_reasoner.py
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
RECENT_QUERY_WINDOW = 3   # require a recent fact.query before treating short reply as correction
SMALLTALK_COOLDOWN = 5    # after 5 smalltalk turns, stop echoing last fact

def _recent_intents(turns: List[Dict[str, str]]) -> List[str]:
    intents = []
    for t in turns:
        # store light-weight intent markers an upper layer might include in meta later
        # for now, we derive nothing; placeholder for 2.10
        pass
    return intents

def reason_about_context(intent: Dict[str, Any], text: str, session_id: str = "default") -> Dict[str, Any]:
    updated = intent.copy()
    turns = get_recent_turns(session_id=session_id)
    last_dom, last_key = get_last_fact(session_id)

    # 1) Topic intro: reset continuity
    topic = extract_topic_intro(text)
    if topic:
        updated["intent"] = "smalltalk"
        updated["__reset_context"] = True
        return updated

    # 2) Negation handling: erase or replace (no "not X" writes)
    if updated.get("intent") == "fact.update" and contains_negation(text):
        # Try to extract a replacement after "not X — Y" or "not X, Y"
        m = re.search(r"\bnot\b[^A-Za-z0-9]+(?P<alt>[\w\s]+)$", text.strip(), re.I)
        if last_dom and last_key and m and m.group("alt").strip():
            updated["domain"] = last_dom
            updated["key"] = last_key
            updated["value"] = m.group("alt").strip()
            updated["confidence"] = 0.95
            return updated
        # otherwise: delete the last fact and ask for clarification
        if last_dom and last_key:
            updated["intent"] = "fact.delete"
            updated["domain"] = last_dom
            updated["key"] = last_key
            updated["value"] = None
            updated["confidence"] = 0.95
            return updated

    # 3) Short-reply correction (guarded): only if a recent fact.query occurred
    if updated.get("intent") in ("smalltalk", "other") and len(text.split()) <= SHORT_REPLY_WORDS:
        # scan the last few turns for an explicit question pattern in user messages
        recent_user_texts = [t["content"].lower() for t in turns[-RECENT_QUERY_WINDOW:] if t["role"] == "user"]
        if any(("what's my" in u or "what is my" in u) for u in recent_user_texts) and last_dom and last_key:
            updated["intent"] = "fact.update"
            updated["domain"] = last_dom
            updated["key"] = last_key
            updated["value"] = text.strip(" .!?")
            updated["confidence"] = 0.95
            return updated

    # 4) Cooldown: if we see a stream of smalltalk, don't keep echoing facts
    if updated.get("intent") == "smalltalk":
        # mark to suppress fact echo downstream (main will just go to router/LLM)
        updated["__suppress_fact_echo"] = True

    # 5) Confidence recovery: if low confidence but key present, prefer graph lookup
    if updated.get("confidence", 1.0) < 0.8 and updated.get("key"):
        dom_guess = updated.get("domain") or detect_domain_from_key(updated["key"])
        updated["domain"] = dom_guess
        updated["intent"] = "fact.query"
        updated["confidence"] = 0.9

    return updated

def build_context_block(query: str, session_id: str = "default") -> str:
    # kept simple; main already merges additional context
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