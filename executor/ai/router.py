# executor/ai/router.py
from __future__ import annotations
import os
from typing import Any, Dict, List
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DEFAULT_MODEL = os.getenv("ROUTER_MODEL") or os.getenv("DEFAULT_MODEL") or "gpt-4o"
BOOST_ENABLED = os.getenv("CORTEX_BOOST_ENABLED", "false").lower() in ("1", "true", "yes")
BOOST_MODEL = os.getenv("CORTEX_BOOST_MODEL", "gpt-5")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

_client = OpenAI(api_key=OPENAI_API_KEY)

def _pick_model(boost: bool) -> str:
    if boost and BOOST_ENABLED:
        return BOOST_MODEL
    return DEFAULT_MODEL


def respond(text: str, boost: bool = False, system: str | None = None,
            context: list[Dict[str, str]] | None = None, **kwargs: Any) -> str:
    """
    Unified chat response handler with memory/context awareness.
    """
    model = _pick_model(boost)
    messages: List[Dict[str, str]] = []

    if system:
        messages.append({"role": "system", "content": system})

    # ✅ include prior context turns in the conversation
    if context:
        # ensure context is a list of {role, content}
        for m in context:
            if isinstance(m, dict) and "role" in m and "content" in m:
                messages.append(m)
            elif isinstance(m, (list, tuple)) and len(m) == 2:
                role, content = m
                messages.append({"role": role, "content": content})
            else:
                messages.append({"role": "system", "content": str(m)})

    # add current user message
    messages.append({"role": "user", "content": text})

    resp = _client.chat.completions.create(model=model, messages=messages, **kwargs)
    msg = resp.choices[0].message
    content = getattr(msg, "content", "") or ""
    if isinstance(content, list):
        content = "".join(
            [c.get("text", "") if isinstance(c, dict) else str(c) for c in content]
        )
    return content

# PATCH START — backward-compatible wrapper for older imports
def chat(text: str, boost: bool = False, system: str | None = None, **kwargs: Any) -> str:
    """
    Legacy compatibility wrapper.
    Mirrors respond() so existing API routes importing 'chat' won't break.
    """
    return respond(text, boost=boost, system=system, **kwargs)
# PATCH END