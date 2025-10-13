# executor/core/language_intent.py
from __future__ import annotations
import os, re
from typing import Literal
from openai import OpenAI

# Supported categories
IntentType = Literal["declaration", "question", "command", "meta", "other"]

# Initialize optional LLM client
_client = None
try:
    _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
except Exception:
    _client = None

_MODEL = os.getenv("CORTEX_INTENT_MODEL", "gpt-4o-mini")

# --------------------------------------------------------------------
# Lightweight intent classifier
# --------------------------------------------------------------------
def classify_language_intent(text: str) -> IntentType:
    """
    Return one of: declaration, question, command, meta, or other.
    Uses fast heuristics first; falls back to an LLM classification
    when available and necessary.
    """
    t = (text or "").strip().lower()
    if not t:
        return "other"

    # --- Heuristic fast paths (99% of input)
    if re.search(r"^(who|what|where|when|why|how)\b", t) or t.endswith("?"):
        return "question"

    if re.search(r"^(forget|delete|remove|clear|reset|undo)\b", t):
        return "meta"

    if re.search(r"^(please|do|can|could|would|find|search|open|start|run|tell|show)\b", t):
        return "command"

    # Declarative forms ("My X is Y", "Our company uses FastAPI", etc.)
    if re.search(r"^(my|our|the|this|that|it|he|she|they|there's|i\s*(am|'m)|we\s*(are|'re))\b", t):
        return "declaration"

    # --- LLM fallback for ambiguous language
    if _client is not None:
        try:
            resp = _client.chat.completions.create(
                model=_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Classify the following message as one of: "
                            "declaration, question, command, meta, or other. "
                            "Respond with just the single word."
                        ),
                    },
                    {"role": "user", "content": text},
                ],
                max_tokens=2,
                temperature=0,
            )
            result = (resp.choices[0].message.content or "").strip().lower()
            if result in {"declaration", "question", "command", "meta", "other"}:
                return result  # safe canonical class
        except Exception:
            pass

    return "other"