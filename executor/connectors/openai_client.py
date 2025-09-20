"""
OpenAI Responses API connector for Executor with persistent memory integration,
error handling, budget usage logging, and self-repair on failures.
"""

import os
import math
from typing import Any, Dict, List
from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

# Memory helpers
from executor.plugins.conversation_manager import conversation_manager as cm
# Budget monitor
from executor.plugins.budget_monitor import budget_monitor
# Self-repair
from executor.utils import self_repair

# Load .env
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY missing from .env")

# Models
REPL_MODEL = os.environ.get("CORTEX_REPL_MODEL", "gpt-4o-mini")   # fast & cheap
HEAVY_MODEL = os.environ.get("CORTEX_HEAVY_MODEL", "gpt-5")       # heavy lifting

client = OpenAI(api_key=OPENAI_API_KEY)


def _estimate_tokens_from_messages(messages: List[Dict[str, str]]) -> int:
    if not messages:
        return 0
    chars = sum(len(m.get("content") or "") for m in messages)
    return max(1, math.ceil(chars / 4))


def _call_model(messages: List[Dict[str, str]], model: str) -> Any:
    return client.responses.create(
        model=model,
        input=messages,
        store=False,
    )


def ask_executor(prompt: str, plugin_name: str = "cortex", *, heavy: bool = False, _retry_on_repair: bool = True) -> Dict[str, Any]:
    """
    Ask GPT with persistent memory:
      - Builds messages with handle_repl_turn (system facts + user input)
      - Calls Responses API
      - Records assistant reply
      - Logs tokens to budget
      - On error, triggers self-repair once and retries the same prompt
    """
    model = HEAVY_MODEL if heavy else REPL_MODEL

    def _one_turn() -> Dict[str, Any]:
        turn = cm.handle_repl_turn(
            current_input=prompt,
            history=cm.get_history(plugin_name),
            session=plugin_name,
            limit=10,
        )
        messages = turn["messages"]
        if not messages:
            raise RuntimeError("[ask_executor] No messages built")
        resp = _call_model(messages, model=model)

        out_text = getattr(resp, "output_text", None) or ""
        if not out_text:
            # defensive parse
            try:
                for item in resp.output:
                    if getattr(item, "type", "") == "message":
                        for c in item.content:
                            if getattr(c, "type", "") == "output_text":
                                out_text = c.text or ""
                                break
            except Exception:
                pass

        cm.record_assistant(plugin_name, out_text)

        # budget logging
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
            pass

        return {
            "status": "ok",
            "assistant_output": out_text,
            "messages": messages,
            "raw": resp,
        }

    try:
        return _one_turn()

    except OpenAIError as e:
        # Attempt self-repair once, then retry
        err_ctx = {"error_type": "OpenAIError", "message": str(e)}
        if _retry_on_repair:
            repair = self_repair.attempt_self_repair(err_ctx)
            if repair.get("status") == "ok":
                # try once more, no infinite recursion
                return ask_executor(prompt, plugin_name=plugin_name, heavy=heavy, _retry_on_repair=False)
        return {"status": "error", **err_ctx}

    except Exception as e:
        # Attempt self-repair once, then retry
        err_ctx = {"error_type": type(e).__name__, "message": str(e)}
        if _retry_on_repair:
            repair = self_repair.attempt_self_repair(err_ctx)
            if repair.get("status") == "ok":
                return ask_executor(prompt, plugin_name=plugin_name, heavy=heavy, _retry_on_repair=False)
        return {"status": "error", **err_ctx}
