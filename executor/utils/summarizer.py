# executor/utils/summarizer.py
"""
Automatic summarization module for Cortex long-term memory.

Creates periodic condensed summaries of chat history and stores them
in the vector database for fast semantic recall, without deleting raw data.
"""

from __future__ import annotations
import time
from executor.utils.memory import recall_context
from executor.utils.vector_memory import store_summary
from executor.ai.router import chat as chat_llm

# --- Configuration ---
SUMMARY_INTERVAL = 200  # summarize every 200 message pairs
SUMMARY_PROMPT = (
    "You are Cortex's archival process. Summarize the following "
    "conversation history into key facts, preferences, goals, and knowledge. "
    "Preserve useful details but keep it concise:\n\n{}"
)


def summarize_if_needed() -> None:
    """
    Condense recent memory into a summary block.
    Safe to call often — only triggers when enough new exchanges exist.
    """
    try:
        context = recall_context(limit=SUMMARY_INTERVAL * 2)
        if len(context) < SUMMARY_INTERVAL * 2:
            return  # not enough new data yet

        joined = "\n".join(f"{m['role']}: {m['content']}" for m in context[-SUMMARY_INTERVAL:])
        summary = chat_llm(SUMMARY_PROMPT.format(joined), boost=False)

        store_summary(summary)
        print(f"[Memory] Added summary block at {time.ctime()}")
    except Exception as e:
        # Non-fatal: summarizer should never interrupt chat flow
        print("[Memory] Summarizer skipped:", e)