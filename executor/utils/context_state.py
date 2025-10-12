from __future__ import annotations
import json, time
from pathlib import Path
from typing import Any, Dict

_STATE = Path(__file__).parent / "context_state.json"

def load_state() -> Dict[str, Any]:
    if _STATE.exists():
        try:
            return json.loads(_STATE.read_text())
        except Exception:
            pass
    return {
        "utc_now": int(time.time()),
        "timezone": "UTC",
        "local_time_str": "",
        "last_known_location": {"city": "", "lat": None, "lon": None},
    }

def save_state(state: Dict[str, Any]) -> None:
    try:
        _STATE.write_text(json.dumps(state, indent=2))
    except Exception:
        pass

def set_location(city: str, lat: float, lon: float) -> None:
    st = load_state()
    st["last_known_location"] = {"city": city or "", "lat": lat, "lon": lon}
    save_state(st)

def set_local_time(local_time_str: str, timezone: str = "UTC") -> None:
    st = load_state()
    st["utc_now"] = int(time.time())
    st["timezone"] = timezone or "UTC"
    st["local_time_str"] = local_time_str or ""
    save_state(st)