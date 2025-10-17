"""
executor/core/context_reasoner.py
---------------------------------
Phase 2.13c — Context Reasoner with tone-aware relational explanations.
"""

from __future__ import annotations
import re
from itertools import groupby
from typing import Any, Dict, List, Optional

from executor.utils.preference_graph import get_preferences, get_dislikes
from executor.utils.inference_graph import list_inferred_preferences
from executor.utils.relationship_graph import related_for_item, normalize_term, explain_relationship
from executor.utils.personality_adapter import style_response
from executor.utils.turn_memory import get_recent_turns

# ---------------- Cosmetic helpers ----------------
def _deduplicate_and_pretty(items: List[str]) -> str:
    norm = [re.sub(r"\s+", " ", i.strip().lower()) for i in items if i.strip()]
    norm = [k for k, _ in groupby(sorted(norm))]
    if not norm:
        return ""
    if len(norm) == 1:
        return norm[0]
    if len(norm) == 2:
        return f"{norm[0]} and {norm[1]}"
    return ", ".join(norm[:-1]) + f", and {norm[-1]}"

# ---------------- Core reasoning ----------------
def reason_about_context(
    query: str | dict,
    *_args,
    session_id: Optional[str] = None,
    tone: Optional[str] = None,
    **_kwargs,
) -> Dict[str, Any]:
    """
    Merges explicit + inferred preferences, retrieves relationships,
    and returns a tone-styled reply.
    """
    # Normalize input
    if isinstance(query, dict):
        query = query.get("text") or query.get("query") or str(query)
    q = (query or "").lower().strip()

    # Temporal recall
    if re.search(r"(?i)\bwhat\s+did\s+i\s+(say|tell)\b", q):
        turns = get_recent_turns(session_id=session_id, limit=8)
        recall_text = "; ".join([t["content"] for t in turns if "content" in t][-6:])
        reply = f"Here’s what we discussed recently: {recall_text}"
        return {"reply": style_response(reply, tone)}

    # Domain detection (loose)
    if any(k in q for k in ["layout", "ui", "interface", "design"]):
        dom = "ui"; title = "layout styles"
    elif any(k in q for k in ["food", "eat", "dish", "cuisine"]):
        dom = "food"; title = "foods"
    elif any(k in q for k in ["color", "palette", "hue", "shade"]):
        dom = "color"; title = "colors"
    else:
        dom = None; title = "things"

    prefs = get_preferences(domain=dom, min_strength=0.0) if dom else get_preferences()
    inferred = list_inferred_preferences(domain=dom) if dom else list_inferred_preferences()

    likes = [p["item"] for p in prefs if p["polarity"] > 0]
    dislikes = [p["item"] for p in prefs if p["polarity"] < 0]
    likes += [p["item"] for p in inferred if p["polarity"] >= 0]
    dislikes += [p["item"] for p in inferred if p["polarity"] < 0]

    like_str = _deduplicate_and_pretty(likes)
    dislike_str = _deduplicate_and_pretty(dislikes)

    # Relational Q: "what goes with ..."
    m = re.search(r"(?i)\bwhat\s+go(?:es)?\s+with\s+(.+)$", q)
    if m:
        seed = normalize_term(m.group(1))
        rels = related_for_item(seed, src_domain_hint=dom or None, limit=8)
        if not rels:
            return {"reply": style_response(f"I don't yet have associations for {seed}.", tone)}
        tops = []
        for r in rels:
            exp = explain_relationship(r["src_domain"], r["dst_domain"])
            tops.append(f"{r['dst_item']} ({r['dst_domain']}) {exp}")
        joined = "; ".join(tops)
        reply = f"{seed.title()} goes well with {joined}."
        return {"reply": style_response(reply, tone)}

    # Standard recall
    if not like_str and not dislike_str:
        return {"reply": style_response(f"I don’t have any {title} preferences stored yet.", tone)}
    if like_str and not dislike_str:
        return {"reply": style_response(f"You like these {title}: {like_str}.", tone)}
    if dislike_str and not like_str:
        return {"reply": style_response(f"You don’t like these {title}: {dislike_str}.", tone)}

    reply = f"You like these {title}: {like_str}. And you don’t like {dislike_str}."
    return {"reply": style_response(reply, tone)}

# Back-compat stub
def build_context_block(*args, **kwargs):
    return {"context": "deprecated"}