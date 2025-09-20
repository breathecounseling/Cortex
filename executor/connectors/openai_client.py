"""
OpenAI Responses API connector for Executor with persistent memory integration.
"""

import os
from typing import Any, Dict, List
from dotenv import load_dotenv
from openai import OpenAI

# Import the simplified conversation_manager functions
from executor.plugins.conversation_manager import conversation_manager as cm

# Load .env
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY missing from .env")

client = OpenAI(api_key=OPENAI_API_KEY)


def ask_executor(prompt: str, plugin_name: str = "cortex") -> Dict[str, Any]:
    """
    Ask GPT with persistent memory:
      - Builds messages with handle_repl_turn (system facts + user input)
      - Calls Responses API
      - Records assistant reply
    """
    # Build turn with prior history
    turn = cm.handle_repl_turn(
        current_input=prompt,
        history=cm.get_history(plugin_name),
        session=plugin_name,
        limit=10,
    )
    messages = turn["messages"]

    if not messages:
        raise RuntimeError("[ask_executor] No messages built")

    # Call GPT
    resp = client.responses.create(
        model="gpt-5",        # for faster REPL you can swap to "gpt-4o-mini"
        input=messages,
        store=False,
    )

    # Normalize assistant output
    out_text = getattr(resp, "output_text", None) or ""
    if not out_text:
        try:
            for item in resp.output:
                if getattr(item, "type", "") == "message":
                    for c in item.content:
                        if getattr(c, "type", "") == "output_text":
                            out_text = c.text or ""
                            break
        except Exception:
            pass

    # Persist assistant reply
    cm.record_assistant(plugin_name, out_text)

    return {
        "assistant_output": out_text,
        "messages": messages,
        "raw": resp,
    }


if __name__ == "__main__":
    print("Test run:")
    r1 = ask_executor("Remember this: my favorite color is green")
    print("Assistant:", r1["assistant_output"])
    r2 = ask_executor("What is my favorite color?")
    print("Assistant:", r2["assistant_output"])
