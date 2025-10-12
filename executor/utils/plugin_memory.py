from __future__ import annotations
import json, sqlite3
from pathlib import Path
from typing import Dict, Any

_BASE = Path(__file__).parent.parent / "plugins_mem"

def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

class PluginMemory:
    def __init__(self, namespace: str):
        self.ns = namespace.replace("/", "_")
        self.root = _BASE / self.ns
        _ensure_dir(self.root)
        self.db = self.root / "memory.db"
        self.state = self.root / "state.json"
        self._init_db()

    def _init_db(self) -> None:
        _ensure_dir(self.root)
        conn = sqlite3.connect(self.db)
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS facts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            k TEXT, v TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS notes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT
        )""")
        conn.commit(); conn.close()

    def add_fact(self, k: str, v: str) -> None:
        conn = sqlite3.connect(self.db)
        c = conn.cursor()
        c.execute("INSERT INTO facts(k, v) VALUES (?,?)", (k, v))
        conn.commit(); conn.close()

    def add_note(self, text: str) -> None:
        conn = sqlite3.connect(self.db)
        c = conn.cursor()
        c.execute("INSERT INTO notes(text) VALUES (?)", (text,))
        conn.commit(); conn.close()

    def summarize(self, limit: int = 5) -> str:
        conn = sqlite3.connect(self.db); c = conn.cursor()
        c.execute("SELECT k, v FROM facts ORDER BY id DESC LIMIT ?", (limit,))
        facts = [f"{k}: {v}" for k, v in c.fetchall()]
        c.execute("SELECT text FROM notes ORDER BY id DESC LIMIT ?", (limit,))
        notes = [t for (t,) in c.fetchall()]
        conn.close()
        if not facts and not notes:
            return ""
        return "Facts:\n- " + "\n- ".join(facts) + \
            ("\nNotes:\n- " + "\n- ".join(notes) if notes else "")

    def load_state(self) -> Dict[str, Any]:
        if self.state.exists():
            try:
                return json.loads(self.state.read_text())
            except Exception:
                pass
        return {}

    def save_state(self, d: Dict[str, Any]) -> None:
        try:
            self.state.write_text(json.dumps(d, indent=2))
        except Exception:
            pass

def for_mode(mode: str) -> PluginMemory:
    return PluginMemory(namespace=f"mode_{mode or 'default'}")