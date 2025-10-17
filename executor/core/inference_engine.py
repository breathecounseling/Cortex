"""
executor/core/inference_engine.py
---------------------------------
Contextual inference engine for Phase 2.12.
"""

import json
from typing import Any, Dict, List
from executor.utils.preference_graph import get_preferences
from executor.utils.inference_graph import upsert_inferred_preference
from executor.ai.router import chat as brain_chat

SYSTEM_PROMPT = (
    "You are Echo's reasoning engine. Given explicit user preferences, "
    "infer related implicit traits and tendencies. "
    "Respond strictly as a JSON list of objects: "
    "[{\"domain\":\"ui\",\"item\":\"soft palette\",\"polarity\":1,\"confidence\":0.9}, ...]"
)

def infer_contextual_preferences(session_id: str = "default") -> List[Dict[str, Any]]:
    prefs = get_preferences(min_strength=0.0)
    if not prefs:
        return []
    facts_str = json.dumps(prefs, indent=2)
    prompt = f"{SYSTEM_PROMPT}\n\nUser preferences:\n{facts_str}"
    try:
        response = brain_chat(prompt)
        data = json.loads(response) if response.strip().startswith("[") else []
    except Exception as e:
        print("[InferenceEngineError]", e)
        data = []
    for item in data:
        domain = item.get("domain", "misc")
        key = item.get("item")
        pol = int(item.get("polarity", 0))
        conf = float(item.get("confidence", 0.5))
        upsert_inferred_preference(domain, key, pol, conf)
    print(f"[Inference] stored {len(data)} inferred preferences.")
    return data