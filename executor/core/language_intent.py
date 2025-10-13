# executor/core/language_intent.py
from __future__ import annotations
import os, re
from typing import Literal, Optional, Dict
try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore

IntentType = Literal["declaration", "question", "command", "meta", "other"]

_client = None
try:
    if OpenAI:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
except Exception:
    _client = None

_MODEL = os.getenv("CORTEX_INTENT_MODEL", "gpt-4o-mini")

def classify_language_intent(text: str) -> IntentType:
    t = (text or "").strip().lower()
    if not t:
        return "other"
    # Heuristics first
    if re.search(r"^(who|what|where|when|why|how)\b", t) or t.endswith("?"):
        return "question"
    if re.search(r"^(forget|delete|remove|clear|reset|undo)\b", t):
        return "meta"
    if re.search(r"^(please|do|can|could|would|find|search|open|start|run|tell|show|add|create|make|plan)\b", t):
        return "command"
    if re.search(r"^(my|our|the|this|that|it|he|she|they|i\b|we\b|there's)\b", t):
        return "declaration"
    # LLM fallback (optional)
    if _client:
        try:
            resp = _client.chat.completions.create(
                model=_MODEL,
                messages=[
                    {"role": "system", "content": "Classify as one word: declaration, question, command, meta, or other."},
                    {"role": "user", "content": text},
                ],
                max_tokens=2,
                temperature=0,
            )
            out = (resp.choices[0].message.content or "").strip().lower()
            if out in {"declaration", "question", "command", "meta", "other"}:
                return out  # type: ignore
        except Exception:
            pass
    return "other"

# Scoped location/travel extractor
_LOC_HOME = re.compile(r"\b(i\s+live\s+in|my\s+home\s+is\s+in)\s+(?P<city>.+)$", re.I)
_LOC_CURRENT = re.compile(r"\b(i'?m\s+(in|at|staying\s+in)|i\s+am\s+(in|at)|i'?m\s+visiting)\s+(?P<city>.+)$", re.I)
_LOC_TRIP = re.compile(r"\b(i'?m\s+planning\s+(a\s+)?trip\s+to|i\s+plan\s+to\s+go\s+to|i'?m\s+going\s+to)\s+(?P<city>.+)$", re.I)

def extract_location_or_trip(text: str) -> Optional[Dict[str, str]]:
    """
    Returns {"kind": "home"|"current"|"trip", "value": <city>} or None.
    We keep it heuristic and fast; LLM fallback can be added later.
    """
    t = (text or "").strip()
    m = _LOC_HOME.search(t)
    if m:
        return {"kind": "home", "value": m.group("city").strip().rstrip(".!?")}
    m = _LOC_CURRENT.search(t)
    if m:
        return {"kind": "current", "value": m.group("city").strip().rstrip(".!?")}
    m = _LOC_TRIP.search(t)
    if m:
        return {"kind": "trip", "value": m.group("city").strip().rstrip(".!?")}
    return None