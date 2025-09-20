"""
OpenAI Responses API connector for Executor with persistent memory integration,
error handling, and budget usage logging.
"""

import os
import math
from typing import Any, Dict, List
from dotenv import load_dotenv
from openai import OpenAI
from openai.error import OpenAIError

# Memory helpers (simplified conversation manager)
from executor.plugins.conversation_manager import conversation_manager as cm
# Budget monitor (new plugin)
from executor.plugins.budget_monitor import budget_monitor

# Load .env
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY missing from .env")

# Models
REPL_MODEL = os.environ.get("CORTEX_REPL_MODEL", "gpt-4o-mini")   # fast & cheap for REPL
HEAVY_MODEL = os.environ.get("CORTEX_HEAVY_MODEL", "gpt-5")       # use for big builds if needed

client = OpenAI(api_key=OPENAI_API_KEY)


def _estimate_tokens_from_messages(messages: List[Dict[str, str]]) -> int:
    # fallback estimator if API doesn't return usage
    if not messages:
        return 0
    chars = sum(len(m.get("content") or "") for m in messages)
    return max(1, math.ceil(chars / 4))  # ~4 chars/token heuristic


def ask_executor(prompt: str, plugin_name: str = "cortex", *, heavy: bool = False) -> Dict[str, Any]:
    """
    Ask GPT with persistent memory:
      - Builds messages with handle_repl_turn (system facts + user input)
      - Calls Responses API (fast model by default; heavy model if heavy=True)
      - Records assistant reply
      - Logs token usage to budget_monitor
      - Returns structured result or error dict
    """
    model = HEAVY_MODEL if heavy else REPL_MODEL

    try:
        # Build turn with prior history (bullet facts in system + new user input)
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
            model=model,
            input=messages,
            store=False,
        )

        # Extract assistant text
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

        # Budget usage logging
        # Prefer API usage; fallback to rough estimate
        used_tokens = 0
        try:
            u = getattr(resp, "usage", None)
            if u:
                used_tokens = int(getattr(u, "total_tokens", 0) or 0)
                if not used_tokens:
                    it = int(getattr(u, "input_tokens", 0) or 0)
                    ot = int(getattr(u, "output_tokens", 0) or 0)
                    used_tokens = it + ot
            if not used_tokens:
                used_tokens = _estimate_tokens_from_messages(messages + [{"role": "assistant", "content": out_text}])
        except Exception:
            used_tokens = _estimate_tokens_from_messages(messages + [{"role": "assistant", "content": out_text}])

        try:
            budget_monitor.record_usage(used_tokens)
        except Exception:
            pass  # never block REPL on budget write

        return {
            "status": "ok",
            "assistant_output": out_text,
            "messages": messages,
            "raw": resp,
        }

    except OpenAIError as e:
        return {
            "status": "error",
            "error_type": "OpenAIError",
            "message": str(e),
        }
    except Exception as e:
        return {
            "status": "error",
            "error_type": type(e).__name__,
            "message": str(e),
        }
