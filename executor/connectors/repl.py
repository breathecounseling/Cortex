from __future__ import annotations
from pathlib import Path
import json

from executor.audit.logger import get_logger, initialize_logging
from executor.utils.memory import init_db_if_needed

logger = get_logger(__name__)

QUESTIONS_FILE = Path(".executor") / "memory" / "repl_questions.json"

def _load_questions() -> list[str]:
    if not QUESTIONS_FILE.exists():
        return []
    try:
        return json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

def _save_questions(questions: list[str]) -> None:
    QUESTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUESTIONS_FILE.write_text(json.dumps(questions, indent=2), encoding="utf-8")

def main() -> None:
    initialize_logging()
    init_db_if_needed()
    logger.info("Executor — chat naturally. Type 'quit' to exit.")
    # REPL loop omitted here — keep your existing one if present.
    # This drop-in ensures consistent init and safe file I/O for question queue.

def add_question(q: str) -> None:
    qs = _load_questions()
    qs.append(q)
    _save_questions(qs)
    logger.info("[Butler] Question added.")

def _show_questions():
    qs = _load_questions()
    if not qs:
        logger.info("[Butler] No pending questions.")
        return
    logger.info(f"[Butler] You still have {len(qs)} pending question(s).")
    for q in qs:
        logger.info(f"- {q}")

def _skip_questions():
    logger.info("[Butler] Questions skipped for now.")