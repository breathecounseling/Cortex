# PATCH START — 2.8.1 value sanitizer
import re

def sanitize_value(value: str) -> str:
    """Trim trailing filler words and punctuation, preserving meaning."""
    if not value:
        return value
    fillers = {"now", "instead", "currently", "today", "tonight", "at the moment"}
    words = value.strip().rstrip(".!?").split()
    if words and words[-1].lower() in fillers:
        words = words[:-1]
    return " ".join(words).strip()
# PATCH END