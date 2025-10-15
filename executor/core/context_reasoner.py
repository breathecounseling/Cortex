"""
executor/core/context_reasoner.py
---------------------------------
Context Reasoner — short-term conversational reasoning engine for Echo.

Purpose:
    • Interpret user intent in the context of recent conversation.
    • Detect implicit corrections, follow-ups, and topic continuity.
    • Merge short-term (turn) memory + long-term (graph) memory into reasoning context.
"""

from __future__ import annotations
import time, re, json
from typing import Dict, Any, Optional, List

from executor.utils.turn_memory import get_recent_turns, get_recent_context_text
from executor.utils.session_context import get_last_fact
from executor.utils import memory_graph as gmem


def reason_about_context(intent: Dict[str, Any], text: str, session_id: str = "default") -> Dict[str, Any]:
    """
    Given a semantic intent and the raw text, adjust it based on conversation context.
    Returns a possibly modified intent dict.
    """
    updated_intent = intent.copy()
    turns = get_recent_turns(session_id=session_id)
    last_dom, last_key = get_last_fact(session_id)

    # --- 1️⃣  Implicit correction: short replies after a query ---
    if updated_intent["intent"] in ("smalltalk", "other") and len(text.split()) <= 3:
        if last_dom and last_key:
            print(f"[ContextReasoner] Reinterpreting short reply as correction for {last_dom}.{last_key}")
            updated_intent["intent"] = "fact.update"
            updated_intent["domain"] = last_dom
            updated_intent["key"] = last_key
            updated_intent["value"] = text.strip(" .!?")
            updated_intent["confidence"] = 0.95
            return updated_intent

    # --- 2️⃣  Location follow-up detection ---
    if updated_intent["intent"] == "location.update" and not updated_intent.get("scope"):
        # Determine if this is "home" or "current" based on last question
        if turns and any("where do i live" in t["content"].lower() for t in turns[-3:]):
            updated_intent["scope"] = "home"
            updated_intent["key"] = "home"
        elif turns and any("where am i" in t["content"].lower() for t in turns[-3:]):
            updated_intent["scope"] = "current"
            updated_intent["key"] = "current"

    # --- 3️⃣  Confidence recovery ---
    if updated_intent.get("confidence", 1.0) < 0.8 and updated_intent.get("key"):
        dom_guess = updated_intent.get("domain") or gmem.detect_domain_from_key(updated_intent["key"])
        node = gmem.get_node(dom_guess, updated_intent["key"])
        if node and node.get("value"):
            print(f"[ContextReasoner] Low confidence revalidated from graph ({dom_guess}.{updated_intent['key']})")
            updated_intent["domain"] = dom_guess
            updated_intent["intent"] = "fact.query"
            updated_intent["confidence"] = 0.95

    # --- 4️⃣  Topic continuity check ---
    if turns:
        recent_text = " ".join(t["content"].lower() for t in turns[-5:])
        if updated_intent["intent"] == "smalltalk":
            if any(kw in recent_text for kw in ["color", "food", "home", "trip", "project", "idea"]):
                # maintain continuity with last relevant topic
                if last_dom and last_key:
                    updated_intent["intent"] = "fact.query"
                    updated_intent["domain"] = last_dom
                    updated_intent["key"] = last_key
                    updated_intent["confidence"] = 0.9

    return updated_intent


def build_context_block(query: str, session_id: str = "default") -> str:
    """
    Compose a full context block (recent turns + relevant facts)
    for inclusion in GPT-5 prompts.
    """
    # short-term recall
    turn_text = get_recent_context_text(limit=10, session_id=session_id)

    # known facts
    try:
        facts = gmem.list_facts()
        fact_text = json.dumps(facts)
    except Exception:
        fact_text = "{}"

    context_block = (
        f"Recent conversation:\n{turn_text}\n\n"
        f"Known user facts: {fact_text}\n\n"
        f"Current query: {query.strip()}"
    )
    return context_block