# executor/utils/docket.py
from __future__ import annotations
import os
import json
import uuid
from datetime import datetime
from typing import List, Dict, Any

class Docket:
    """
    Tiny persistent task docket for prerequisites/steps the model proposes.
    Stored at .executor/memory/<namespace>_docket.json
    """
    def __init__(self, namespace: str = "repl"):
        self.namespace = namespace
        self._dir = os.path.join(".executor", "memory")
        os.makedirs(self._dir, exist_ok=True)
        self._path = os.path.join(self._dir, f"{namespace}_docket.json")
        self._data: Dict[str, Any] = {"tasks": []}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except Exception:
                self._data = {"tasks": []}

    def _save(self) -> None:
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    def list_tasks(self) -> List[Dict[str, Any]]:
        return list(self._data.get("tasks", []))

    def add(self, title: str, priority: str = "normal") -> str:
        tid = uuid.uuid4().hex[:8]
        task = {
            "id": tid,
            "title": title,
            "priority": priority if priority in {"low", "normal", "high"} else "normal",
            "status": "todo",
            "created": datetime.utcnow().isoformat(),
        }
        self._data.setdefault("tasks", []).append(task)
        self._save()
        return tid

    def complete(self, task_id: str) -> bool:
        for t in self._data.get("tasks", []):
            if t["id"] == task_id:
                t["status"] = "done"
                self._save()
                return True
        return False

    def clear_done(self) -> int:
        before = len(self._data.get("tasks", []))
        self._data["tasks"] = [t for t in self._data.get("tasks", []) if t.get("status") != "done"]
        self._save()
        return before - len(self._data["tasks"])
