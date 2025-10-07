# executor/utils/config.py
from __future__ import annotations
import os
from pathlib import Path
from typing import Any, Dict
from dotenv import load_dotenv

# Load environment once
load_dotenv()

ROOT_DIR = Path(os.getcwd())
EXECUTOR_DIR = ROOT_DIR / ".executor"
MEMORY_DIR = EXECUTOR_DIR / "memory"
SCHEMAS_DIR = MEMORY_DIR / "schemas"
LOGS_DIR = EXECUTOR_DIR / "logs"

MEMORY_DB_PATH = MEMORY_DIR / "memory.db"
MEMORY_LOG_JSONL = MEMORY_DIR / "memory_log.jsonl"

def ensure_dirs() -> None:
    for d in (EXECUTOR_DIR, MEMORY_DIR, SCHEMAS_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)

def get_config() -> Dict[str, Any]:
    """
    Centralized accessor for common paths & settings.
    """
    ensure_dirs()
    return {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
        "ROUTER_MODEL": os.getenv("ROUTER_MODEL", "gpt-4o-mini"),
        "AUTONOMOUS_MODE": os.getenv("AUTONOMOUS_MODE", "false").lower() in ("1", "true", "yes"),
        "STANDBY_MINUTES": int(os.getenv("STANDBY_MINUTES", "15")),
        "MEMORY_DB_PATH": str(MEMORY_DB_PATH),
        "MEMORY_LOG_JSONL": str(MEMORY_LOG_JSONL),
        "SCHEMA_INIT_SQL": str(SCHEMAS_DIR / "init.sql"),
        "LOGS_DIR": str(LOGS_DIR),
    }
