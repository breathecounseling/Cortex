# executor/connectors/openai_client.py
from __future__ import annotations
import os
import json
from typing import Optional, Dict, Any, List

from dotenv import load_dotenv
from openai import OpenAI

from executor.utils.error_handler import ExecutorError

# Load .env from project root
load_dotenv()

class OpenAIClient:
    def __init__(self, model: str = "gpt-4o-mini"):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not found in environment")
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def chat(
        self,
        messages: List[Dict[str, str]],
        response_format: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Low-level chat call to OpenAI API.
        Returns assistant content as a string.
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format=response_format or {"type": "text"},
        )
        return response.choices[0].message.content or ""

    def generate_structured(
        self,
        *,
        system: str,
        user: str,
        schema: Optional[Dict[str, Any]] = None,
        attachments: Optional[List[str]] = None,
        max_retries: int = 2,
    ) -> str:
        """
        Enforce JSON-only replies with at least one file entry. Retries if empty/malformed.
        """
        messages: List[Dict[str, str]] = [{"role": "system", "content": system}]

        if attachments:
            for path in attachments:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        code = f.read()
                    messages.append({
                        "role": "user",
                        "content": f"<FILE path='{path}'>\n{code}\n</FILE>",
                    })
                except Exception:
                    continue

        messages.append({"role": "user", "content": user})
        messages.append({
            "role": "system",
            "content": (
                "Return ONLY JSON. Keys: rationale, changelog, files[]. "
                "Each files[] item: path (string), content (string), kind ('code'|'test'|'doc'). "
                "Never return an empty string."
            ),
        })

        for attempt in range(max_retries + 1):
            out = self.chat(messages, response_format={"type": "json_object"})
            if out and out.strip().startswith("{"):
                return out
            messages.append({
                "role": "system",
                "content": (
                    "Previous output was empty/invalid. You MUST return valid JSON now, "
                    "with at least one non-empty file under 'files'. No prose."
                ),
            })

        raise ExecutorError("empty_model_output", details={"why": "exhausted retries"})