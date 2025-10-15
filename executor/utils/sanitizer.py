"""
executor/utils/sanitizer.py
----------------------------
Cleans user-provided values before storage.
Removes filler words and trailing temporal phrases.
"""

from __future__ import annotations

FILLERS = {
    "now", "currently", "instead", "today", "tonight",
    "right now", "at the moment", "for the moment",
    "right", "momentarily", "for now", "as of now", "at present"
}


def sanitize_value(value: str | None) -> str | None:
    """Trim punctuation and trailing filler phrases."""
    if not value:
        return value
    s = value.strip().rstrip(".!?")
    tokens = s.split()
    if not tokens:
        return s

    # check last 3, then 2, then 1 tokens
    last3 = " ".join(tokens[-3:]).lower() if len(tokens) >= 3 else ""
    last2 = " ".join(tokens[-2:]).lower() if len(tokens) >= 2 else ""
    last1 = tokens[-1].lower()

    if last3 in FILLERS:
        tokens = tokens[:-3]
    elif last2 in FILLERS:
        tokens = tokens[:-2]
    elif last1 in FILLERS:
        tokens = tokens[:-1]

    return " ".join(tokens).strip()