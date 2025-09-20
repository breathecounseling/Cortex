"""
Budget Monitor plugin
Tracks token usage and enforces a daily budget limit.
"""

import os
import json
from datetime import date
from pathlib import Path

BUDGET_PATH = Path(os.environ.get("BUDGET_MONITOR_PATH", ".executor/budget.json"))
DAILY_LIMIT = int(os.environ.get("BUDGET_MONITOR_DAILY_LIMIT", "100000"))  # tokens/day default

def _load() -> dict:
    if not BUDGET_PATH.exists():
        return {"date": str(date.today()), "used": 0}
    try:
        return json.loads(BUDGET_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"date": str(date.today()), "used": 0}

def _save(data: dict) -> None:
    BUDGET_PATH.parent.mkdir(parents=True, exist_ok=True)
    BUDGET_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

def record_usage(tokens: int) -> dict:
    """Record token usage for today."""
    data = _load()
    today = str(date.today())
    if data.get("date") != today:
        data = {"date": today, "used": 0}
    data["used"] += int(tokens)
    _save(data)
    return data

def check_budget() -> dict:
    """Check budget status: { ok, used, limit }"""
    data = _load()
    used = int(data.get("used", 0))
    return {"ok": used <= DAILY_LIMIT, "used": used, "limit": DAILY_LIMIT}

def run():
    return {"status": "ok", "plugin": "budget_monitor", "budget": check_budget()}
