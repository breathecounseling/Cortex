"""
executor/utils/sanitizer.py
----------------------------
Cleans user-provided values before storage.
Removes filler words and trailing or inline temporal phrases.
"""

from __future__ import annotations
import re

# Common filler phrases that add no semantic value to stored facts
FILLERS = {
    "now", "currently", "instead", "today", "tonight",
    "right now", "at the moment", "for the moment",
    "momentarily", "for now", "as of now", "at present"
}


def sanitize_value(value: str | None) -> str | None:
    """
    Normalize and clean a user-provided value before saving to the graph.
    Removes punctuation and common temporal fillers (e.g. "right now", "at the moment").
    Works even when the filler appears mid-phrase, such as "Chicago right now".
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

    # Clean up stray punctuation and double spaces left by removals
    s = re.sub(r"\s{2,}", " ", s)      # collapse multiple spaces
    s = re.sub(r"\s+,", ",", s)        # fix space before commas
    s = re.sub(r",\s*,", ",", s)       # double commas
    s = re.sub(r"\s+$", "", s)         # trailing spaces

    return s.strip()