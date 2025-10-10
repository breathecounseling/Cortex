from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Any, List

_PROFILE = Path(__file__).parent.parent.parent / "utils" / "user_profile.json"

def _ensure_profile() -> dict:
    if _PROFILE.exists():
        try:
            return json.loads(_PROFILE.read_text())
        except Exception:
            pass
    prof = {
        "identity": {"name": "", "roles": []},
        "values": [], "goals": [], "style": {"tone":"friendly","risk":"moderate"},
        "learning": [], "feedback_summary": ""
    }
    try: _PROFILE.write_text(json.dumps(prof, indent=2))
    except Exception: pass
    return prof

def can_handle(intent: str) -> bool:
    return intent.strip().lower() in {"proactive_ideas","innovation"}

def describe_capabilities() -> str:
    return "Generates proactive suggestions (scaffold; disabled by default)."

def handle(payload: Dict[str, Any]) -> Dict[str, Any]:
    prof = _ensure_profile()
    hints: List[str] = []
    if prof.get("goals"):
        hints.append(f"Goals: {', '.join(g.get('goal','') for g in prof['goals'])}")
    if prof.get("learning"):
        hints.append(f"Learning: {', '.join(prof['learning'])}")
    summary = "Innovation ideas are not enabled yet. " + (" | ".join(hints) if hints else "")
    return {"status":"ok","ideas": [], "summary": summary}