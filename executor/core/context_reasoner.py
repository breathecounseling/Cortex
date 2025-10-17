"""
executor/core/context_reasoner.py
---------------------------------
Phase 2.12c — Context Reasoner with cosmetic deduplication, grammar fixes,
and backward-compatible signature for session_id.
"""

from __future__ import annotations
import re
from itertools import groupby
from typing import Any, Dict, List, Optional

from executor.utils.preference_graph import get_preferences, get_dislikes
from executor.utils.inference_graph import list_inferred_preferences


# ---------------------------------------------------------------------
# Cosmetic helpers
# ---------------------------------------------------------------------
def _deduplicate_and_pretty(items: List[str]) -> str:
    """
    Remove near-duplicate items (case-insensitive, trimmed)
    and return a grammatically clean string like "A, B, and C".
    """
    norm = [re.sub(r"\s+", " ", i.strip().lower()) for i in items if i.strip()]
    norm = [k for k, _ in groupby(sorted(norm))]
    if not norm:
        return ""
    if len(norm) == 1:
        return norm[0]
    if len(norm) == 2:
        return f"{norm[0]} and {norm[1]}"
    return ", ".join(norm[:-1]) + f", and {norm[-1]}"


# ---------------------------------------------------------------------
# Core reasoning
# ---------------------------------------------------------------------
def reason_about_context(
    query: str,
    *_args,
    session_id: Optional[str] = None,
    **_kwargs
) -> Dict[str, Any]:
    """
    Simplified context reasoner:
    merges explicit + inferred preferences and returns human-readable text.
    Accepts extra args for backward compatibility.
    """
    q = (query or "").lower().strip()
    prefs = get_preferences()
    inferred = list_inferred_preferences()

    # Determine domain of interest from query
    if any(k in q for k in ["layout", "ui", "interface", "design"]):
        dom = "ui"
        title = "layout styles"
    elif any(k in q for k in ["food", "eat", "dish"]):
        dom = "food"
        title = "foods"
    elif any(k in q for k in ["color", "palette", "hue", "shade"]):
        dom = "color"
        title = "colors"
    else:
        dom = None
        title = "things"

    # Collect preferences
    likes = [
        p["item"]
        for p in prefs
        if p["polarity"] > 0 and (dom is None or p["domain"] == dom)
    ]
    dislikes = [
        p["item"]
        for p in prefs
        if p["polarity"] < 0 and (dom is None or p["domain"] == dom)
    ]

    # Add inferred ones
    likes += [
        p["item"]
        for p in inferred
        if p["polarity"] >= 0 and (dom is None or p["domain"] == dom)
    ]
    dislikes += [
        p["item"]
        for p in inferred
        if p["polarity"] < 0 and (dom is None or p["domain"] == dom)
    ]

    # Deduplicate + prettify
    like_str = _deduplicate_and_pretty(likes)
    dislike_str = _deduplicate_and_pretty(dislikes)

    # Build reply
    if not like_str and not dislike_str:
        reply = f"I don’t have any {title} preferences stored yet."
    elif like_str and not dislike_str:
        reply = f"You like these {title}: {like_str}."
    elif dislike_str and not like_str:
        reply = f"You don’t like these {title}: {dislike_str}."
    else:
        reply = (
            f"You like these {title}: {like_str}. "
            f"And you don’t like {dislike_str}."
        )

    print(f"[ContextReasoner] Generated reply → {reply}")
    return {"reply": reply}


# ---------------------------------------------------------------------
# Legacy stub for backward compatibility
# ---------------------------------------------------------------------
def build_context_block(*args, **kwargs):
    """
    Legacy placeholder for backward compatibility.
    No longer used in Phase 2.12c+ — kept to satisfy old imports.
    """
    return {"context": "deprecated"}