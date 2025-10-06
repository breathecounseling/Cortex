from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from executor.audit.logger import get_logger, initialize_logging
from executor.utils.memory import init_db_if_needed, remember

logger = get_logger(__name__)

@dataclass
class Task:
    id: int
    title: str
    status: str = "pending"
    meta: Dict[str, Any] = field(default_factory=dict)

class Docket:
    """
    In-memory docket with namespace-scoped global store (test-friendly).
    """
    _GLOBAL: Dict[str, Dict[str, Any]] = {}

    def __init__(self, namespace: Optional[str] = None) -> None:
        initialize_logging()
        init_db_if_needed()
        self.namespace = namespace or "default"
        if self.namespace not in self._GLOBAL:
            self._GLOBAL[self.namespace] = {"counter": 0, "tasks": []}

    # --- helpers ---
    def _next_id(self) -> int:
        self._GLOBAL[self.namespace]["counter"] += 1
        return self._GLOBAL[self.namespace]["counter"]

    def _tasks(self) -> List[Dict[str, Any]]:
        return self._GLOBAL[self.namespace]["tasks"]

    # --- API expected by tests ---
    def add(self, title: str, **meta: Any) -> int:
        tid = self._next_id()
        task = {"id": tid, "title": title, "status": "pending", "meta": meta}
        self._tasks().append(task)
        try:
            remember("system", "task_added", title, source="docket", confidence=1.0)
        except Exception:
            pass
        logger.info(f"Docket add: {title}")
        return tid

    def list(self, status: Optional[str] = None) -> List[Task]:
        items = self._tasks()
        if status:
            items = [t for t in items if t["status"] == status]
        return [Task(**t) for t in items]

    # compatibility expected by tests
    def list_tasks(self) -> List[Dict[str, Any]]:
        return list(self._tasks())

    def update(self, tid: int | str, *, title: Optional[str] = None, status: Optional[str] = None) -> bool:
        for t in self._tasks():
            if str(t["id"]) == str(tid):
                if title is not None:
                    t["title"] = title
                if status is not None:
                    t["status"] = status
                return True
        return False

    def complete(self, title: str) -> bool:
        for t in self._tasks():
            if t["title"] == title:
                t["status"] = "done"
                try:
                    remember("system", "task_completed", title, source="docket", confidence=1.0)
                except Exception:
                    pass
                logger.info(f"Docket complete: {title}")
                return True
        return False

    def remove(self, title: str) -> bool:
        tasks = self._tasks()
        for i, t in enumerate(tasks):
            if t["title"] == title:
                tasks.pop(i)
                logger.info(f"Docket remove: {title}")
                return True
        return False

    def remove_by_id(self, tid: int | str) -> bool:
        tasks = self._tasks()
        for i, t in enumerate(tasks):
            if str(t["id"]) == str(tid):
                tasks.pop(i)
                logger.info(f"Docket remove id: {tid}")
                return True
        return False