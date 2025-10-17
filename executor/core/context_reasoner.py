"""
executor/core/context_reasoner.py
---------------------------------
Phase 2.13 — Context Reasoner (cosmetic dedup + relational associations)

- Handles dict or string input (compat)
- Merges explicit + inferred preferences
- Pulls relational associations to enrich replies
"""

from __future__ import annotations
import re
from itertools import groupby
from typing import Any, Dict, List, Optional

from executor.utils.preference_graph import get_preferences
from executor.utils.inference_graph import list_inferred_preferences
from executor.utils.relationship_graph import list_relations, related_for_item


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
    **_kwargs,
) -> Dict[str, Any]:
    # Normalize input
    if isinstance(query, dict):
        query = query.get("text") or query.get("query") or str(query)
    q = (query or "").lower().strip()

    prefs = get_preferences()
    inferred = list_inferred_preferences()

    # Determine domain of interest
    if any(k in q for k in ["layout", "ui", "interface", "design"]):
        dom = "ui"; title = "layout styles"
    elif any(k in q for k in ["food", "eat", "dish", "cuisine"]):
        dom = "food"; title = "foods"
    elif any(k in q for k in ["color", "palette", "hue", "shade"]):
        dom = "color"; title = "colors"
    else:
        dom = None; title = "things"

    # Collect preferences by domain
    likes = [p["item"] for p in prefs if p["polarity"] > 0 and (dom is None or p["domain"] == dom)]
    dislikes = [p["item"] for p in prefs if p["polarity"] < 0 and (dom is None or p["domain"] == dom)]
    likes += [p["item"] for p in inferred if p["polarity"] >= 0 and (dom is None or p["domain"] == dom)]
    dislikes += [p["item"] for p in inferred if p["polarity"] < 0 and (dom is None or p["domain"] == dom)]

    # If question looks like "what goes with X"
    m = re.search(r"(?i)\b(what\s+goes\s+with|what\s+pairs\s+with|what\s+works\s+with)\s+(.+)$", q)
    if m:
        seed = m.group(2).strip(" ?.!").lower()
        rels = related_for_item(seed, src_domain_hint=dom or None, limit=10)
        suggestions = [f"{r['dst_item']} ({r['dst_domain']})" for r in rels]
        s = _deduplicate_and_pretty(suggestions)
        if s:
            return {"reply": f"{seed} goes well with {s}."}
        return {"reply": f"I don't yet have associations for {seed}."}

    # Standard recall + relational enrichment
    like_str = _deduplicate_and_pretty(likes)
    dislike_str = _deduplicate_and_pretty(dislikes)

    # Pull top associated items *from existing likes* (if a specific domain asked)
    enrichments: List[str] = []
    if dom and likes:
        seen = set()
        for item in likes[:3]:
            rels = related_for_item(item, src_domain_hint=dom, limit=5)
            for r in rels:
                key = (r["dst_domain"], r["dst_item"])
                if key not in seen:
                    seen.add(key)
                    enrichments.append(f"{r['dst_item']} ({r['predicate']})")
    enrich_str = _deduplicate_and_pretty(enrichments)

    # Build reply
    if not like_str and not dislike_str:
        reply = f"I don’t have any {title} preferences stored yet."
    elif like_str and not dislike_str:
        reply = f"You like these {title}: {like_str}."
    elif dislike_str and not like_str:
        reply = f"You don’t like these {title}: {dislike_str}."
    else:
        reply = (f"You like these {title}: {like_str}. "
                 f"And you don’t like {dislike_str}.")

    if enrich_str:
        reply += f" These also tend to go with your taste: {enrich_str}."

    print(f"[ContextReasoner] Generated reply → {reply}")
    return {"reply": reply}


# ---------------- Legacy stub (compat) ----------------
def build_context_block(*args, **kwargs):
    return {"context": "deprecated"}