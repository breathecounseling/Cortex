"""
OpenAI Responses API connector for Executor.
Provides ask_executor() for freeform prompts and tool calls.
"""

import os
import json
from dotenv import load_dotenv
from openai import OpenAI

# Load .env from repo root
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY missing from .env")

client = OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_INSTRUCTIONS = (
    "You are Cortex Executor, an AI system that writes and edits Python plugins. "
    "If the user request is vague, ask clarifying questions. "
    "If code is provided with an error log, fix only the broken parts while preserving working code. "
    "When outputting code, return ONLY the complete corrected file."
)

def ask_executor(prompt: str, tools: list = None, thread_id: str = "default"):
    """
    High-level interface to the OpenAI Responses API.
    Returns a dict with either response_text or function_call.
    """
    response = client.responses.create(
        model="gpt-5",
        instructions=SYSTEM_INSTRUCTIONS,
        input=prompt,
        tools=tools or [],
        store=False
    )

    # If plain text output
    out_text = getattr(response, "output_text", None) or ""
    result = {"status": "ok", "response_text": out_text, "raw": response}

    # Inspect function calls if present
    for item in response.output:
        if item.type == "function_call":
            try:
                args = json.loads(item.arguments)
            except Exception:
                args = {}
            result = {
                "status": "function_call",
                "name": item.name,
                "arguments": args,
                "raw": response
            }
            break

    return result

if __name__ == "__main__":
    # Quick test
    print(ask_executor("Write a hello world Python function"))
