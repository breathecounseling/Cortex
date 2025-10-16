"""
executor/utils/sanitizer.py
----------------------------
Cleans user-provided values before storage.
Removes filler words and trailing or inline temporal phrases.
Fixes dangling punctuation (e.g. "Denver,." → "Denver").
"""

from __future__ import annotations
import re

FILLERS = {
    "now", "currently", "instead", "today", "tonight",
    "right now", "at the moment", "for the moment",
    "momentarily", "for now", "as of now", "at present"
}


def sanitize_value(value: str | None) -> str | None:
    """
    Normalize and clean a user-provided value before saving to the graph.
    Removes punctuation and common temporal fillers (e.g. "right now", "at the moment"),
    and fixes leftover commas or periods.
    """
    if not value:
        return value

    s = value.strip().rstrip(".!?")

    # Remove temporal filler phrases anywhere near the end or embedded in value
    s = re.sub(
        r"\b("
        r"right\s+now|at\s+the\s+moment|for\s+the\s+moment|"
        r"for\s+now|as\s+of\s+now|momentarily|currently|now"
        r")\b",
        "",
        s,
        flags=re.I,
    )

    # Remove extra punctuation or dangling commas created by the removals
    s = re.sub(r"\s*,\s*(?:\.|,)*$", "", s)          # comma at end
    s = re.sub(r"[,.]+\s*$", "", s)                  # leftover ., or , at end
    s = re.sub(r"\s{2,}", " ", s)                    # collapse multiple spaces
    s = re.sub(r"\s+,", ",", s)                      # fix spaces before commas
    s = re.sub(r",\s*,", ",", s)                     # merge double commas
    s = re.sub(r"\s+$", "", s)                       # trailing spaces

    return s.strip()