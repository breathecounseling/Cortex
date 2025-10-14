# executor/core/semantic_intent.py
from __future__ import annotations
import os, re, json
from typing import Any, Dict, Optional

try:
    from openai import OpenAI
    _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
except Exception:
    _client = None

INTENT_MODEL = os.getenv("CORTEX_INTENT_MODEL") or "gpt-4o-mini"

_INTENT_SYSTEM = """You analyze a single user message and output compact JSON:
{
  "intent": "fact.update" | "fact.query" | "fact.delete" | "location.update" | "location.query" | "smalltalk" | "command",
  "domain": string | null,        // e.g. "color", "food", "location"
  "key": string | null,           // e.g. "favorite color", "favorite food", "home"
  "value": string | null,         // value to set/read/delete (if relevant)
  "scope": string | null,         // for location: "home"|"current"|"trip" else null
  "confidence": number            // 0.0 - 1.0
}
Rules:
- "Change my ... to X", "Update my ... to X", "Set my ... to X", "No, it's X", "Actually, it's X", "I changed my mind ... it's X" => intent = "fact.update".
- "What's my ...", "What is my ..." => "fact.query".
- "Forget my ..." => "fact.delete".
- Location phrases:
  * "I live in CITY" => location.update, domain=location, key=home, value=CITY, scope=home
  * "I'm in CITY" or "I'm currently in CITY" => location.update, key=current, scope=current
  * "I'm going to CITY" or "trip to CITY" => location.update, key=trip, scope=trip
  * "Where do I live?" => location.query, key=home
  * "Where am I (now)?" => location.query, key=current
  * "Where am I going?" => location.query, key=trip
- If no clear domain/key but phrasing is "No, it's X" or "Actually, it's X", classify fact.update with domain/key = null (caller may fill from session context).
- If unsure, choose "smalltalk" with low confidence.
Return ONLY the JSON.
"""

# --- Regex fallback when API key or model unavailable or on error ---
_RX_UPDATE = re.compile(
    r"(?i)^(?:i\s+changed\s+my\s+mind[,.]?\s*(?:about|on)?\s+(?P<key1>[\w\s]+)\s*(?:to)?\s+(?P<val1>[^.?!]+)$"
    r"|change\s+my\s+(?P<key2>[\w\s]+)\s+to\s+(?P<val2>[^.?!]+)$"
    r"|update\s+my\s+(?P<key3>[\w\s]+)\s+to\s+(?P<val3>[^.?!]+)$"
    r"|set\s+my\s+(?P<key4>[\w\s]+)\s+to\s+(?P<val4>[^.?!]+)$"
    r"|no[,.\s]*it'?s\s+(?P<val5>[^.?!]+)$"
    r"|actually[,.\s]*it'?s\s+(?P<val6>[^.?!]+)$)"
)

_RX_QUERY = re.compile(r"(?i)^(what('?s| is)\s+my\s+(?P<qkey>[\w\s]+)\??)$")
_RX_DELETE = re.compile(r"(?i)^forget\s+(?:my|the)\s+(?P<dkey>[\w\s]+)$")

# Location updates/queries
_RX_LOC_HOME   = re.compile(r"(?i)\b(i\s+live\s+in|my\s+home\s+is\s+in)\s+(?P<city>[\w\s,]+)")
_RX_LOC_CURR   = re.compile(r"(?i)\b(i'?m\s+(in|at|staying\s+in|visiting)|i\s+am\s+(in|at))\s+(?P<city>[\w\s,]+)")
_RX_LOC_TRIP   = re.compile(r"(?i)\b(i'?m\s+(going\s+to|planning\s+(?:a\s+)?trip\s+to)|trip\s+to)\s+(?P<city>[\w\s,]+)")
_RX_LOC_Q_TRIP = re.compile(r"(?i)\b(where\s+am\s+i\s+going|trip\s+destination|where\s+is\s+my\s+trip)\b")
_RX_LOC_Q_CURR = re.compile(r"(?i)\b(where\s+am\s+i(\s+now)?|current\s+location)\b")
_RX_LOC_Q_HOME = re.compile(r"(?i)\b(where\s+do\s+i\s+live|home\s+location|where\s+is\s+my\s+home)\b")

def _canon_key(k: Optional[str]) -> Optional[str]:
    if not k: return k
    k = k.strip().lower()
    k = re.sub(r"[\s_]+", " ", k)
    return k.strip()

def analyze(text: str, history: Optional[list[dict]] = None) -> Dict[str, Any]:
    t = (text or "").strip()
    if not t:
        return {"intent": "smalltalk", "domain": None, "key": None, "value": None, "scope": None, "confidence": 0.1}

    # Location first (clear patterns)
    m = _RX_LOC_HOME.search(t)
    if m:
        return {"intent": "location.update", "domain": "location", "key": "home", "value": m.group("city").strip(), "scope": "home", "confidence": 0.95}
    m = _RX_LOC_CURR.search(t)
    if m:
        return {"intent": "location.update", "domain": "location", "key": "current", "value": m.group("city").strip(), "scope": "current", "confidence": 0.95}
    m = _RX_LOC_TRIP.search(t)
    if m:
        return {"intent": "location.update", "domain": "location", "key": "trip", "value": m.group("city").strip(), "scope": "trip", "confidence": 0.95}
    if _RX_LOC_Q_TRIP.search(t):
        return {"intent": "location.query", "domain": "location", "key": "trip", "value": None, "scope": "trip", "confidence": 0.9}
    if _RX_LOC_Q_CURR.search(t):
        return {"intent": "location.query", "domain": "location", "key": "current", "value": None, "scope": "current", "confidence": 0.9}
    if _RX_LOC_Q_HOME.search(t):
        return {"intent": "location.query", "domain": "location", "key": "home", "value": None, "scope": "home", "confidence": 0.9}

    # Update forms
    m = _RX_UPDATE.match(t)
    if m:
        key = m.group("key1") or m.group("key2") or m.group("key3") or m.group("key4")
        val = m.group("val1") or m.group("val2") or m.group("val3") or m.group("val4") or m.group("val5") or m.group("val6")
        key = _canon_key(key) if key else None
        return {"intent": "fact.update", "domain": None, "key": key, "value": (val or "").strip(), "scope": None, "confidence": 0.9}

    # Query
    m = _RX_QUERY.match(t)
    if m:
        key = _canon_key(m.group("qkey"))
        return {"intent": "fact.query", "domain": None, "key": key, "value": None, "scope": None, "confidence": 0.85}

    # Delete
    m = _RX_DELETE.match(t)
    if m:
        key = _canon_key(m.group("dkey"))
        return {"intent": "fact.delete", "domain": None, "key": key, "value": None, "scope": None, "confidence": 0.9}

    # Try LLM if available for richer inference (domain inference)
    if _client:
        try:
            messages = [
                {"role":"system","content":_INTENT_SYSTEM},
                {"role":"user","content":t},
            ]
            resp = _client.chat.completions.create(model=INTENT_MODEL, messages=messages, temperature=0)
            raw = resp.choices[0].message.content or "{}"
            jstart, jend = raw.find("{"), raw.rfind("}")
            parsed = json.loads(raw[jstart:jend+1]) if jstart != -1 and jend != -1 else {}
            intent = str(parsed.get("intent","smalltalk"))
            domain = parsed.get("domain")
            key = _canon_key(parsed.get("key"))
            val = parsed.get("value")
            scope = parsed.get("scope")
            conf = float(parsed.get("confidence") or 0.7)
            return {"intent": intent, "domain": domain, "key": key, "value": val, "scope": scope, "confidence": conf}
        except Exception as e:
            print("[SemanticIntentLLMError]", e)

    # Fallback smalltalk
    return {"intent": "smalltalk", "domain": None, "key": None, "value": None, "scope": None, "confidence": 0.4}