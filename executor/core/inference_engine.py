"""
executor/core/inference_engine.py
---------------------------------
Phase 2.12b — Contextual inference engine (robust JSON parsing)

- Ensures LLM responses are parsed even if wrapped in text.
- Prints [Inference] Input summary for Fly log visibility.
- Stores inferred preferences in /data/memory.db.
"""

from __future__ import annotations
import json, re
from typing import Any, Dict, List

from executor.utils.preference_graph import get_preferences
from executor.utils.inference_graph import upsert_inferred_preference
from executor.ai.router import chat as brain_chat

# ---------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are Echo's reasoning engine. "
    "Given the user's explicit preferences below, infer implicit traits, "
    "aesthetic tendencies, and related cross-domain preferences. "
    "Respond ONLY with a valid JSON array — no extra text, no commentary. "
    "If nothing can be inferred, return []. "
    "Each object must have keys: domain, item, polarity (+1 or -1), confidence (0–1)."
)

# ---------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------
def infer_contextual_preferences(session_id: str = "default") -> List[Dict[str, Any]]:
    """
    Pull explicit preferences, query the model for implicit inferences,
    and persist them in inferred_preferences.
    """
    # 1️⃣ Gather all explicit preferences (any domain)
    prefs = get_preferences(domain=None, min_strength=0.0)
    if not prefs:
        print("[Inference] No explicit preferences found; skipping inference.")
        return []

    # 2️⃣ Prepare model input
    facts_str = json.dumps(prefs, indent=2)
    prompt = f"{SYSTEM_PROMPT}\n\nExplicit user preferences:\n{facts_str}\n\nJSON:"

    print(f"[Inference] Input summary: {len(prefs)} preferences → domains:",
          sorted({p['domain'] for p in prefs}))

    # 3️⃣ Query the LLM
    try:
        response = brain_chat(prompt).strip()
    except Exception as e:
        print("[InferenceEngineError] Model call failed:", e)
        return []

    # 4️⃣ Extract JSON list safely
    json_match = re.search(r"\[[\s\S]*\]", response)
    if json_match:
        try:
            data = json.loads(json_match.group(0))
        except Exception as e:
            print("[InferenceParseError]", e)
            data = []
    else:
        print("[InferenceWarning] No JSON array detected in model response.")
        data = []

    # 5️⃣ Persist in DB
    stored = 0
    for item in data:
        domain = (item.get("domain") or "misc").strip().lower()
        key = (item.get("item") or "").strip()
        if not key:
            continue
        pol = int(item.get("polarity", 0))
        conf = float(item.get("confidence", 0.5))
        try:
            upsert_inferred_preference(domain, key, pol, conf)
            stored += 1
        except Exception as e:
            print("[InferencePersistError]", e)

    print(f"[Inference] Stored {stored} inferred preferences.")
    return data