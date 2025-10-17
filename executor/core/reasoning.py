"""
executor/core/reasoning.py
--------------------------
Phase 2.10b: Reasoning & Communication scaffold

Responsibilities:
- Infer high-level goals from free-form text (heuristics; GPT-backed enrichment later)
- Identify unknowns (gaps) to ask clarifying questions
- Build a compact reasoning frame Echo can use to steer the conversation
"""

from __future__ import annotations
import re
from typing import Dict, List, Optional

from executor.utils.turn_memory import get_recent_turns
from executor.utils.vector_memory import retrieve_topic_summaries
from executor.utils.session_context import get_topic, set_topic


_GOAL_RX = re.compile(
    r"(?i)\b(i\s*(?:want|need|plan|would\s+like)\s+to\s+(?:build|create|make|ship|develop)|"
    r"let'?s\s+build|can\s+you\s+build|help\s+me\s+build)\b"
)

_FEATURE_HINTS = [
    ("auth", ["login", "signup", "oauth", "identity", "auth"]),
    ("persistence", ["database", "db", "store", "save", "persist"]),
    ("api", ["api", "rest", "graphql", "endpoint"]),
    ("ui", ["ui", "screen", "page", "frontend", "react", "view"]),
    ("jobs", ["cron", "background", "scheduler", "worker", "queue"]),
]


def _clean(text: str) -> str:
    return (text or "").strip().rstrip(".!?").strip()


def infer_goal_from_text(text: str) -> Optional[str]:
    """Return the coarse 'goal' phrase, e.g., 'build a fitness tracker'."""
    t = _clean(text)
    if not t:
        return None
    # Try to extract after 'to <verb>' or 'let's <verb>'
    m = re.search(r"(?i)\b(?:to\s+(build|create|make|develop)\s+(?P<what>.+))", t)
    if m and m.group("what"):
        return _clean(m.group("what"))
    m = re.search(r"(?i)\b(?:let'?s\s+(build|create|make|develop)\s+(?P<what>.+))", t)
    if m and m.group("what"):
        return _clean(m.group("what"))
    # Fallback: if sentence starts with 'build/create/make ...'
    m = re.search(r"(?i)\b(build|create|make|develop)\s+(?P<what>.+)", t)
    if m and m.group("what"):
        return _clean(m.group("what"))
    return None


def detect_unknowns(goal: Optional[str], recent_turns: List[Dict], summaries: List[str]) -> List[str]:
    """
    Heuristic gaps: platform, scope, data model, timeline, target user, success metric.
    Refines later with GPT-backed enrichment.
    """
    unknowns = []
    haystack = " ".join([_clean(t["content"]) for t in recent_turns] + summaries).lower()
    checks = {
        "target user": any(k in haystack for k in ["for kids", "for teams", "for freelancers", "b2b", "b2c"]),
        "platform": any(k in haystack for k in ["ios", "android", "mobile", "web", "desktop"]),
        "data model": any(k in haystack for k in ["schema", "table", "entity", "model"]),
        "scope": any(k in haystack for k in ["mvp", "v1", "phase", "milestone"]),
        "success metric": any(k in haystack for k in ["kpi", "metric", "retention", "conversion", "goal"]),
        "timeline": any(k in haystack for k in ["deadline", "timeline", "eta", "launch"]),
    }
    for item, present in checks.items():
        if not present:
            unknowns.append(item)
    # Small refinement: if goal references a domain, remove obviously irrelevant unknowns
    if goal:
        g = goal.lower()
        if "fitness" in g:
            # most fitness apps imply mobile; deprioritize 'platform' only if already stated
            pass
    return unknowns[:5]


def suggest_clarifying_question(goal: Optional[str], unknowns: List[str]) -> str:
    """Return a single, tight clarifying question."""
    if not goal:
        return "What would you like to build? Describe the outcome, not the implementation."
    if unknowns:
        top = unknowns[0]
        if top == "platform":
            return f"Should {goal} be for mobile, web, or both?"
        if top == "target user":
            return f"Who is the primary target user for {goal}?"
        if top == "scope":
            return f"For {goal}, do you want a minimal MVP or include extra features from day one?"
        if top == "data model":
            return f"What core data does {goal} need to track? (e.g., entities and fields)"
        if top == "timeline":
            return f"Do you have a timeline for {goal}? (e.g., MVP date)"
        if top == "success metric":
            return f"How will we measure success for {goal}?"
    # fallback
    return f"To confirm, is the main goal '{goal}'? Any constraints I should know about?"


def extract_feature_hints(text: str) -> List[str]:
    """Scan text for lightweight feature hints (auth, persistence, api, ui, jobs)."""
    t = (text or "").lower()
    hits = []
    for tag, keywords in _FEATURE_HINTS:
        if any(k in t for k in keywords):
            hits.append(tag)
    return hits


def reason_about_goal(text: str, session_id: str) -> Dict:
    """
    Build a reasoning frame from the current input, recent turns, and vector summaries.
    """
    recent_turns = get_recent_turns(session_id=session_id)
    summaries = retrieve_topic_summaries(text, k=3) or []
    goal = infer_goal_from_text(text)
    if not goal:
        # Try to borrow goal or topic from context
        topic = get_topic(session_id)
        if topic:
            goal = topic
    unknowns = detect_unknowns(goal, recent_turns, summaries)
    next_q = suggest_clarifying_question(goal, unknowns)
    feature_hints = extract_feature_hints(text)

    # If goal exists, adopt it as topic to keep the thread coherent
    if goal:
        set_topic(session_id, goal)

    return {
        "goal": goal,
        "unknowns": unknowns,
        "next_question": next_q,
        "feature_hints": feature_hints,
    }


def next_clarifying_reply(frame: Dict) -> str:
    """
    Produce the user-facing clarifying prompt based on the reasoning frame.
    (We keep it minimal here; templates layer can enrich tone.)
    """
    goal = frame.get("goal")
    q = frame.get("next_question")
    if goal and q:
        return f"Goal: {goal}\n{q}"
    if q:
        return q
    return "Tell me more about what you want to build."