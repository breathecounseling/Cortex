from __future__ import annotations
from typing import List, Dict, Any, Optional
import os

from executor.audit.logger import get_logger
from executor.utils.config import get_config
from dotenv import load_dotenv

# External: openai library (you already have it in requirements)
from openai import OpenAI

logger = get_logger(__name__)
load_dotenv()

class OpenAIClient:
    """
    Thin wrapper around OpenAI chat completions.
    Preserves the existing interface used by tests:
      - __init__(model: str | None = None)
      - chat(messages: List[Dict[str, str]]) -> str
    """
    def __init__(self, model: Optional[str] = None):
        cfg = get_config()
        self.api_key = cfg["OPENAI_API_KEY"] or os.getenv("OPENAI_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is missing")
        self.model = model or cfg["ROUTER_MODEL"]
        self._client = OpenAI(api_key=self.api_key)
        logger.debug(f"OpenAIClient initialized with model={self.model}")

    def chat(self, messages: List[Dict[str, str]], **kwargs: Any) -> str:
        """
        Expected to return the assistant text content.
        """
        logger.debug("OpenAIClient.chat called", extra={"message_count": len(messages)})
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            **kwargs,
        )
        # Cope with both message.content (str) and array content
        msg = resp.choices[0].message
        content = getattr(msg, "content", "")
        if isinstance(content, list):
            content = "".join([c.get("text", "") if isinstance(c, dict) else str(c) for c in content])
        return content or ""