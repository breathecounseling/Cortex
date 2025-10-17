"""
executor/core/inference_engine.py
---------------------------------
Phase 2.15 — Adds Next Best Action (NBA) ranking.

- suggest_next_goal(session_id): ranks open + inferred candidates
- infer_related_goals(session_id): tiny heuristic for missing steps
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional
import datetime
from executor.utils.goals import get_open_goals

# --- tiny helper to normalize effort ---
_EFFORT_SCORE = {"small": 2, "medium": 1, "large": 0}

def _deadline_weight(deadline_str: Optional[str]) -> int:
    if not deadline_str: return 0
    try:
        import dateutil.parser as dp
        d = dp.parse(deadline_str, fuzzy=True).date()
        days = (d - datetime.date.today()).days
        if days <= 3: return 2
        if days <= 7: return 1
    except Exception:
        return 0
    return 0

def _score_goal(g: Dict[str, Any]) -> int:
    priority_score = int(g.get("priority") or 2)        # 3 high → better
    effort = (g.get("effort_estimate") or "medium").lower()
    effort_score = _EFFORT_SCORE.get(effort, 1)         # small best
    deadline_score = _deadline_weight(g.get("deadline"))
    return priority_score + effort_score + deadline_score

# --- placeholder inferred suggestions (can expand later) ---
def infer_related_goals(session_id: str) -> List[Dict[str, Any]]:
    """
    Heuristic: if a goal looks like 'write ad copy' and there is no landing page/email follow-up,
    suggest those as soft candidates (status=idea). Not persisted—just candidates for NBA.
    """
    ops = get_open_goals(session_id)
    titles = " ".join([g["title"].lower() for g in ops])
    ideas: List[Dict[str, Any]] = []
    if "ad copy" in titles and "landing page" not in titles:
        ideas.append({"id": None, "title": "Create landing page wireframe", "priority": 2,
                      "effort_estimate": "small", "deadline": None, "status": "idea"})
    if "ad copy" in titles and "email" not in titles:
        ideas.append({"id": None, "title": "Draft follow-up email sequence", "priority": 2,
                      "effort_estimate": "small", "deadline": None, "status": "idea"})
    return ideas

def suggest_next_goal(session_id: str) -> Optional[Dict[str, Any]]:
    open_goals = get_open_goals(session_id)
    inferred = infer_related_goals(session_id)

    candidates = []
    for g in open_goals:
        g2 = dict(g); g2["__score"] = _score_goal(g)
        candidates.append(g2)
    for g in inferred:
        g2 = dict(g); g2["__score"] = _score_goal(g)
        candidates.append(g2)

    if not candidates:
        return None

    ranked = sorted(candidates, key=lambda x: x["__score"], reverse=True)
    top = ranked[0]
    msg = f"Would you like to work on “{top['title']}” next? It looks like a solid quick win."
    return {"intent": "goal.suggest", "reply": msg, "candidate": top}