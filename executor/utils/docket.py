from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from executor.audit.logger import get_logger, initialize_logging
from executor.utils.memory import init_db_if_needed, remember

logger = get_logger(__name__)

@dataclass
class Task:
    title: str
    status: str = "pending"
    meta: Dict[str, Any] = field(default_factory=dict)

class Docket:
    _GLOBAL_TASKS: List[Task] = []

    def __init__(self, namespace: Optional[str] = None) -> None:
        initialize_logging()
        init_db_if_needed()
        self.namespace = namespace
        self._items: List[Task] = Docket._GLOBAL_TASKS

    def add(self, title: str, **meta: Any) -> Task:
        status = "todo" if title.strip().startswith("[idea]") else "pending"
        t = Task(title=title, status=status, meta=meta)
        self._items.append(t)
        remember("system", "task_added", title, source="docket", confidence=1.0)
        logger.info(f"Docket add: {title}")
        return t

    def list(self, status: Optional[str] = None) -> List[Task]:
        if status:
            return [t for t in self._items if t.status == status]
        return list(self._items)

    def list_tasks(self) -> List[Dict[str, Any]]:
        return [t.__dict__ for t in self._items]

    def complete(self, title: str) -> bool:
        for t in self._items:
            if t.title == title:
                t.status = "done"
                remember("system", "task_completed", title, source="docket", confidence=1.0)
                logger.info(f"Docket complete: {title}")
                return True
        return False

    def remove(self, title: str) -> bool:
        for i, t in enumerate(self._items):
            if t.title == title:
                self._items.pop(i)
                logger.info(f"Docket remove: {title}")
                return True
        return False

    # NEW: used when approving/rejecting "[idea]" tasks in tests
    def approve(self, title: str) -> bool:
        for t in self._items:
            if t.title == title:
                t.status = "todo"
                if t.title.startswith("[idea] "):
                    t.title = t.title.replace("[idea] ", "", 1)
                return True
        return False