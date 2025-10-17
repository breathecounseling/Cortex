"""
executor/core/inference_engine.py
---------------------------------
Phase 2.13 — Contextual inference + relationship extraction

- Robust JSON parsing for inferred preferences
- Second pass: infer relationships (pairwise associations)
"""

from __future__ import annotations
import json, re
from typing import Any, Dict, List

from executor.utils.preference_graph import get_preferences
from executor.utils.inference_graph import upsert_inferred_preference
from executor.utils.relationship_graph import upsert_relationship
from executor.ai.router import chat as brain_chat

PREF_PROMPT = (
    "You are Echo's reasoning engine. "
    "Given the user's explicit preferences below, infer implicit traits and tendencies. "
    "Respond ONLY with a JSON array like: "
    "[{\"domain\":\"ui\",\"item\":\"soft palette\",\"polarity\":1,\"confidence\":0.85}, ...] "
    "Return [] if nothing to add."
)

REL_PROMPT = (
    "Given the same preferences, infer pairwise relationships that help design decisions. "
    "Return ONLY a JSON array of objects with keys: "
    "{\"src_domain\":\"ui\",\"src_item\":\"cozy\",\"predicate\":\"associated_with\","
    "\"dst_domain\":\"color\",\"dst_item\":\"warm tones\",\"confidence\":0.8} "
    "Valid predicates: 'associated_with', 'goes_with', 'implies', 'contrasts'. "
    "Return [] if none."
)

def _extract_json_list(text: str) -> List[Dict[str, Any]]:
    text = (text or "").strip()
    m = re.search(r"\[[\s\S]*\]", text)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, list) else []
    except Exception as e:
        print("[InferenceParseError]", e)
        return []

def infer_contextual_preferences(session_id: str = "default") -> List[Dict[str, Any]]:
    # ---- 1) explicit prefs
    prefs = get_preferences(domain=None, min_strength=0.0)
    if not prefs:
        print("[Inference] No explicit preferences found; skipping inference.")
        return []

    facts_str = json.dumps(prefs, indent=2)
    print(f"[Inference] Input summary: {len(prefs)} preferences → domains:",
          sorted({p['domain'] for p in prefs}))

    # ---- 2) inferred preferences
    try:
        pref_resp = brain_chat(f"{PREF_PROMPT}\n\nExplicit preferences:\n{facts_str}\n\nJSON:")
    except Exception as e:
        print("[InferenceEngineError] model(pref):", e)
        pref_resp = "[]"
    pref_list = _extract_json_list(pref_resp)

    stored = 0
    for item in pref_list:
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
            print("[InferencePersistError:pref]", e)
    print(f"[Inference] Stored {stored} inferred preferences.")

    # ---- 3) relationships
    try:
        rel_resp = brain_chat(f"{REL_PROMPT}\n\nExplicit preferences:\n{facts_str}\n\nJSON:")
    except Exception as e:
        print("[InferenceEngineError] model(rel):", e)
        rel_resp = "[]"
    rel_list = _extract_json_list(rel_resp)

    r_stored = 0
    for r in rel_list:
        sdom = (r.get("src_domain") or "misc").strip().lower()
        sitem = (r.get("src_item") or "").strip()
        pred  = (r.get("predicate") or "associated_with").strip().lower()
        ddom = (r.get("dst_domain") or "misc").strip().lower()
        ditem = (r.get("dst_item") or "").strip()
        conf = float(r.get("confidence", 0.6))
        if not sitem or not ditem:
            continue
        try:
            upsert_relationship(sdom, sitem, pred, ddom, ditem, weight=conf, confidence=conf)
            r_stored += 1
        except Exception as e:
            print("[InferencePersistError:rel]", e)
    print(f"[Inference] Stored {r_stored} relationships.")

    return pref_list