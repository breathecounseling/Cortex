"""
executor/utils/dialogue_templates.py
------------------------------------
Lightweight phrasing helpers for reasoning/clarification.
You can expand or swap these with model-backed style later.
"""

from __future__ import annotations
import random

CLARIFY_TEMPLATES = [
    "To make sure I understand, could you clarify: {question}",
    "Quick check: {question}",
    "Before I proceed, {question}",
    "Got it. {question}",
]

CONFIRM_TEMPLATES = [
    "So the goal is '{goal}', correct?",
    "Confirming: '{goal}' — shall I proceed?",
]

def clarifying_line(question: str) -> str:
    t = random.choice(CLARIFY_TEMPLATES)
    return t.format(question=question)

def confirm_line(goal: str) -> str:
    t = random.choice(CONFIRM_TEMPLATES)
    return t.format(goal=goal)