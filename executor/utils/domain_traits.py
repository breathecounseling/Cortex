"""
executor/utils/domain_traits.py
-------------------------------
Registry of domain traits and personality defaults.

Phase 2.12b — Tone inheritance foundation
Allows Echo to automatically adopt tone/personality
based on domain (fitness, journal, creative, etc.).
"""

import json
from pathlib import Path

# Default tone map (can be expanded dynamically)
DEFAULT_DOMAIN_TRAITS = {
    "fitness": {"tone": "motivating and tough"},
    "journal": {"tone": "calm and reflective"},
    "creative": {"tone": "playful and imaginative"},
    "business": {"tone": "focused and strategic"},
    "default": {"tone": "neutral"},
}

TRAITS_PATH = Path("/data/domain_traits.json")


def ensure_domain_traits():
    """Ensure traits file exists with defaults."""
    if not TRAITS_PATH.exists():
        TRAITS_PATH.write_text(json.dumps(DEFAULT_DOMAIN_TRAITS, indent=2))
        print("[DomainTraits] Created default domain_traits.json")
    else:
        # merge in new defaults if file exists but is missing keys
        current = json.loads(TRAITS_PATH.read_text())
        updated = {**DEFAULT_DOMAIN_TRAITS, **current}
        TRAITS_PATH.write_text(json.dumps(updated, indent=2))


def get_domain_tone(domain: str) -> str:
    """Return the preferred tone for a domain."""
    try:
        data = json.loads(TRAITS_PATH.read_text())
        if domain in data:
            return data[domain].get("tone", "neutral")
        return data.get("default", {}).get("tone", "neutral")
    except Exception:
        return "neutral"


def list_domains() -> list[str]:
    """List all known domains."""
    try:
        data = json.loads(TRAITS_PATH.read_text())
        return list(data.keys())
    except Exception:
        return list(DEFAULT_DOMAIN_TRAITS.keys())


# Ensure file exists on import
ensure_domain_traits()