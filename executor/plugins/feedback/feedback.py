from __future__ import annotations
import json, sqlite3
from pathlib import Path
from typing import Dict, Any

DB = Path(__file__).parent / "feedback.db"
CFG = Path(__file__).parent / "feedback_config.json"

def _init():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS feedback(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rating INTEGER,          -- +1 / 0 / -1
        tags TEXT,               -- json list
        note TEXT,
        context_id TEXT,
        source TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit(); conn.close()
    if not CFG.exists():
        CFG.write_text(json.dumps({"base_interval_min": 60, "multiplier": 1.0}, indent=2))

def can_handle(intent: str) -> bool:
    return intent.lower().strip() in {"feedback", "rate", "opinion"}

def describe_capabilities() -> str:
    return "Log user feedback (👍/👎/note) and adapt future ask frequency."

def handle(payload: Dict[str, Any]) -> Dict[str, Any]:
    _init()
    rating = int(payload.get("rating", 0))  # -1,0,1
    tags = payload.get("tags") or []
    note = (payload.get("note") or "").strip()
    context_id = payload.get("context_id") or ""
    source = payload.get("source") or "user"

    # store
    conn = sqlite3.connect(DB); c = conn.cursor()
    c.execute("INSERT INTO feedback(rating, tags, note, context_id, source) VALUES (?,?,?,?,?)",
              (rating, json.dumps(tags), note, context_id, source))
    conn.commit(); conn.close()

    # Adjust ask frequency (simple scaffold; used by scheduler if enabled)
    cfg = json.loads(CFG.read_text())
    mult = float(cfg.get("multiplier", 1.0))
    if "feedback_rate" in tags or "too_often" in tags or "stop_asking" in tags:
        if "stop_asking" in tags:
            mult = 999999.0  # effectively off
        else:
            mult *= 1.5      # slow down
    elif rating > 0 and "ask_more" in tags:
        mult *= 0.9          # slightly more often
    cfg["multiplier"] = max(0.1, min(mult, 1_000_000.0))
    CFG.write_text(json.dumps(cfg, indent=2))

    return {"status": "ok", "message": "Feedback recorded", "next_ask_multiplier": cfg["multiplier"]}