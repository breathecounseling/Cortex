"""
executor/core/context_reasoner.py
---------------------------------
Reasoning layer that interprets context and relational inferences.

2.13b patch:
- Adds fuzzy normalization for queries like “cozy layouts”
- Integrates relationship_graph explanations
"""

from __future__ import annotations
import re
from typing import Dict, Any, Optional
from executor.utils import memory_graph as gmem
from executor.utils.relationship_graph import related_for_item, normalize_term, explain_relationship
from executor.utils.preference_graph import get_preferences, get_dislikes
from executor.utils.turn_memory import get_recent_turns

def reason_about_context(intent: Dict[str, Any], query: str,
                         session_id: Optional[str] = None) -> Dict[str, Any]:
    """Interprets parsed intent within conversational and preference context."""
    q = (query or "").strip().lower()

    # Temporal recall
    if re.search(r"(?i)\bwhat\s+did\s+i\s+(say|tell)\b", q):
        turns = get_recent_turns(session_id=session_id, limit=8)
        recall_text = "; ".join([t["text"] for t in turns])
        return {"intent": "temporal.recall", "reply": f"Here’s what we discussed recently: {recall_text}"}

    # Layout preferences
    if "layout" in q or "layouts" in q:
        prefs = get_preferences("ui", min_strength=0.0)
        if prefs:
            likes = [p["item"] for p in prefs if p["polarity"] > 0]
            reply = f"You like these layout styles: {', '.join(sorted(set(likes)))}."
            return {"intent": "ui.query", "reply": reply}
        return {"intent": "ui.query", "reply": "I don't yet have any layout preferences saved."}

    # Food preferences
    if "food" in q or "foods" in q or "eat" in q:
        likes = [p["item"] for p in get_preferences("food", min_strength=0.0) if p["polarity"] > 0]
        dislikes = [p["item"] for p in get_dislikes("food")]
        if likes or dislikes:
            reply = "You like these foods: " + ", ".join(sorted(set(likes))) if likes else ""
            if dislikes:
                reply += f" And you don’t like {', '.join(sorted(set(dislikes)))}."
            return {"intent": "food.query", "reply": reply.strip()}
        return {"intent": "food.query", "reply": "I don't have enough information about your food preferences yet."}

    # Relational queries with explanations
    if re.search(r"(?i)\bwhat\s+go(es)?\s+with\b", q):
        target = normalize_term(q.split("with")[-1])
        rels = related_for_item(target)
        if not rels:
            return {"intent": "relation.query", "reply": f"I don't yet have associations for {target}."}
        tops = []
        for r in rels:
            exp = explain_relationship(r["src_domain"], r["tgt_domain"])
            tops.append(f"{r['tgt_item']} ({r['tgt_domain']}) {exp}")
        joined = "; ".join(tops)
        return {"intent": "relation.query", "reply": f"{target.title()} goes well with {joined}."}

    # Fallback smalltalk
    return {"intent": "smalltalk", "reply": None}