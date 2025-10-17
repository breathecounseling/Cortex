"""
executor/core/inference_engine.py
---------------------------------
Phase 2.12 — Contextual inference engine

Uses the model to infer implicit preferences and tendencies from
explicit, stored preferences. Results are persisted so reasoning and
orchestration can use them in future turns.
"""

from __future__ import annotations
import json
from typing import Any, Dict, List

from executor.utils.preference_graph import get_preferences
from executor.utils.inference_graph import upsert_inferred_preference
from executor.ai.router import chat as brain_chat

SYSTEM_PROMPT = (
    "You are Echo's reasoning engine.\n"
    "Given the user's explicit preferences (likes/dislikes) below, infer implicit traits,\n"
    "aesthetic tendencies, and related cross-domain preferences. Keep the output factual and conservative.\n"
    "Only return a JSON array with objects of the form:\n"
    "[{\"domain\":\"ui\",\"item\":\"soft palette\",\"polarity\":1,\"confidence\":0.85}, ...]\n"
    "Valid domains include (but are not limited to): ui, color, food, music, decor, style.\n"
    "polarity: +1 for positive affinity, -1 for negative. confidence: 0..1.\n"
)

def infer_contextual_preferences(session_id: str = "default") -> List[Dict[str, Any]]:
    """
    Pull explicit preferences, ask the model for implicit inferences,
    and persist them in inferred_preferences.
    """
    # 1) Gather all explicit preferences (any domain, any strength)
    prefs = get_preferences(domain=None, min_strength=0.0)  # type: ignore
    if not prefs:
        print("[Inference] No explicit preferences; skipping inference.")
        return []

    # 2) Prepare LLM input
    facts_str = json.dumps(prefs, indent=2)
    prompt = f"{SYSTEM_PROMPT}\n\nExplicit preferences:\n{facts_str}\n\nInferred JSON:"

    # 3) Query model
    try:
        response = brain_chat(prompt)
        response = response.strip()
        data = json.loads(response) if response.startswith("[") else []
    except Exception as e:
        print("[InferenceEngineError]", e)
        data = []

    # 4) Persist
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