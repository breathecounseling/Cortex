"""
executor/core/inference_engine.py
---------------------------------
Phase 2.12 — Contextual inference engine

Uses the model to infer implicit preferences, themes, and personality traits
from persistent preferences and facts. Stores them as inferred preferences.
"""

from __future__ import annotations
import json, time
from typing import Dict, Any, List
from executor.utils.inference_graph import upsert_inferred_preference
from executor.utils.preference_graph import get_preferences
from executor.ai.router import chat as brain_chat

SYSTEM_PROMPT = """
You are Echo's reasoning engine.
Given a user's explicit preferences and stored facts, infer deeper, implicit traits.
Infer relationships, aesthetic tendencies, and personality indicators.
Return your reasoning as a structured JSON list of {domain, item, polarity, confidence}.
"""

def infer_contextual_preferences(session_id: str = "default") -> List[Dict[str, Any]]:
    # Step 1: Gather explicit preferences
    prefs = get_preferences(min_strength=0.0)
    if not prefs:
        return []

    # Step 2: Prepare LLM input
    facts_str = json.dumps(prefs, indent=2)
    prompt = f"{SYSTEM_PROMPT}\n\nUser preferences:\n{facts_str}\n\nInfer related implicit preferences."

    # Step 3: Query model
    try:
        response = brain_chat(prompt)
        data = json.loads(response) if response.strip().startswith("[") else []
    except Exception as e:
        print("[InferenceEngineError]", e)
        data = []

    # Step 4: Persist in inference graph
    inferred = []
    for item in data:
        domain = item.get("domain") or "misc"
        key = item.get("item")
        pol = item.get("polarity", 0)
        conf = float(item.get("confidence", 0.5))
        upsert_inferred_preference(domain, key, pol, conf)
        inferred.append(item)
    print(f"[Inference] Stored {len(inferred)} inferred preferences.")
    return inferred