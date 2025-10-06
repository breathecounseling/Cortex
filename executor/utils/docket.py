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
    Simple in-memory docket compatible with the legacy tests.

    API (compat):
      - __init__(namespace="repl")
      - add(title, **meta) -> id
      - list_tasks() -> List[Dict]
      - list(status=None) -> List[Task]
      - update(id, title=None, status=None)
      - complete(id) -> bool
      - remove(id) -> bool
    """

    def __init__(self, namespace: Optional[str] = None) -> None:
        initialize_logging()
        init_db_if_needed()
        self.namespace = namespace or "default"
        self._items: List[Task] = []
        self._next_id: int = 1

    def _next(self) -> int:
        nid = self._next_id
        self._next_id += 1
        return nid

    def add(self, title: str, **meta: Any) -> int:
        tid = self._next()
        task = Task(id=tid, title=title, meta=meta)
        self._items.append(task)
        try:
            remember("system", "task_added", title, source="docket", confidence=1.0)
        except Exception:
            pass
        logger.info(f"Docket add: {title}")
        return tid

    def list(self, status: Optional[str] = None) -> List[Task]:
        if status:
            return [t for t in self._items if t.status == status]
        return list(self._items)

    # legacy helper the tests call
    def list_tasks(self) -> List[Dict[str, Any]]:
        return [
            {"id": t.id, "title": t.title, "status": t.status, "meta": dict(t.meta)}
            for t in self._items
        ]

    def update(self, id: int, *, title: Optional[str] = None, status: Optional[str] = None) -> None:
        for t in self._items:
            if t.id == int(id):
                if title is not None:
                    t.title = title
                if status is not None:
                    t.status = status
                return

    def complete(self, id: int) -> bool:
        for t in self._items:
            if t.id == int(id):
                t.status = "done"
                try:
                    remember("system", "task_completed", t.title, source="docket", confidence=1.0)
                except Exception:
                    pass
                logger.info(f"Docket complete: {t.title}")
                return True
        return False

    def remove(self, id: int) -> bool:
        for i, t in enumerate(self._items):
            if t.id == int(id):
                self._items.pop(i)
                logger.info(f"Docket remove: {t.title}")
                return True
        return False