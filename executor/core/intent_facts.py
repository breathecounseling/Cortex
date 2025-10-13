# executor/core/intent_facts.py
from __future__ import annotations
import os, json
from typing import Any, Dict

try:
    from openai import OpenAI
    _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
except Exception:
    _client = None

INTENT_MODEL = os.getenv("CORTEX_INTENT_MODEL") or "gpt-4o-mini"

_SYSTEM_PROMPT = """You are Cortex's semantic interpreter.
Given a user message, classify whether it:
1. Declares a personal fact about the speaker (e.g. "my favorite color is green"),
2. Asks a question about a personal fact (e.g. "what is my favorite color"),
3. Corrects or updates a fact (e.g. "actually it's blue now"),
4. Or is something else.

Return ONLY valid JSON in this format:
{
  "type": "fact.declaration" | "fact.query" | "fact.correction" | "other",
  "key": string | null,
  "value": string | null
}
Keys should be concise (e.g. "favorite color", "location", "birthday").
If no key/value can be determined, set them to null.
"""

def detect_fact_or_question(text: str) -> Dict[str, Any]:
    """Use the model to classify a message into fact/query/correction/other."""
    text = (text or "").strip()
    if not text:
        return {"type": "other", "key": None, "value": None}

    # fallback if OpenAI not available
    if not _client:
        lowered = text.lower()
        if "my" in lowered and (" is " in lowered or "'s " in lowered):
            parts = lowered.split("my", 1)[-1].strip()
            if " is " in parts:
                key, val = parts.split(" is ", 1)
                return {"type": "fact.declaration", "key": key.strip(), "value": val.strip()}
        if lowered.startswith(("what", "where", "who")) and " my " in lowered:
            key = lowered.split("my", 1)[-1].strip(" ?.")
            return {"type": "fact.query", "key": key, "value": None}
        return {"type": "other", "key": None, "value": None}

    try:
        resp = _client.chat.completions.create(
            model=INTENT_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            max_tokens=120,
            temperature=0.0,
        )
        raw = resp.choices[0].message.content or "{}"
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1:
            return {"type": "other", "key": None, "value": None}
        parsed = json.loads(raw[start:end + 1])
        if not isinstance(parsed, dict):
            return {"type": "other", "key": None, "value": None}
        return {
            "type": parsed.get("type") or "other",
            "key": parsed.get("key"),
            "value": parsed.get("value"),
        }
    except Exception as e:
        print("[IntentFactsError]", e)
        return {"type": "other", "key": None, "value": None}