"""
OpenAI Responses API connector for Executor with:
- Persistent memory
- Fact handling
- Tool calls
- Budget logging
- Error classification + self-repair integration
"""

import os
import math
import json
import re
from typing import Any, Dict, List
from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

from executor.plugins.builder import builder, extend_plugin
from executor.plugins.conversation_manager import conversation_manager as cm
from executor.plugins.conversation_manager.conversation_manager import save_fact
from executor.plugins.budget_monitor import budget_monitor
from executor.utils import error_handler

TOOLS = [
    {
        "type": "function",
        "name": "build_plugin",
        "description": "Create a new Executor plugin.",
        "parameters": {
            "type": "object",
            "properties": {
                "plugin_name": {"type": "string"},
                "purpose": {"type": "string"}
            },
            "required": ["plugin_name", "purpose"]
        }
    },
    {
        "type": "function",
        "name": "extend_plugin",
        "description": "Extend an existing Executor plugin with a new feature.",
        "parameters": {
            "type": "object",
            "properties": {
                "plugin_name": {"type": "string"},
                "new_feature": {"type": "string"}
            },
            "required": ["plugin_name", "new_feature"]
        }
    }
]

# Load .env
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY missing from .env")

REPL_MODEL = os.environ.get("CORTEX_REPL_MODEL", "gpt-4o-mini")
HEAVY_MODEL = os.environ.get("CORTEX_HEAVY_MODEL", "gpt-5")

client = OpenAI(api_key=OPENAI_API_KEY)

def _estimate_tokens_from_messages(messages: List[Dict[str, str]]) -> int:
    chars = sum(len(m.get("content") or "") for m in messages)
    return max(1, math.ceil(chars / 4))

def _call_model(messages: List[Dict[str, str]], model: str) -> Any:
    return client.responses.create(
        model=model,
        input=messages,
        tools=TOOLS,
        store=False,
    )

def _maybe_extract_fact(user_input: str) -> tuple[str, str] | None:
    """Heuristic: if user says 'my favorite X is Y', capture as (X, Y)."""
    m = re.search(r"my favorite ([a-zA-Z ]+) is ([a-zA-Z ]+)", user_input.lower())
    if m:
        key = m.group(1).strip().replace(" ", "_")
        value = m.group(2).strip()
        return key, value
    return None

def ask_executor(prompt: str, plugin_name: str = "cortex", *, heavy: bool = False) -> Dict[str, Any]:
    """Main entrypoint: handles chat, facts, tool calls, and errors with repair."""
    try:
        # Step 1: detect simple facts
        fact = _maybe_extract_fact(prompt)
        if fact:
            entry = save_fact(plugin_name, fact[0], fact[1])
            return {
                "status": "ok",
                "assistant_output": f"Got it! I'll remember your {fact[0].replace('_',' ')} is {fact[1]}.",
                "messages": [],
                "raw": entry
            }

        # Step 2: normal REPL flow
        model = HEAVY_MODEL if heavy else REPL_MODEL
        turn = cm.handle_repl_turn(
            current_input=prompt,
            history=cm.get_history(plugin_name),
            session=plugin_name,
            limit=10,
        )
        messages = turn["messages"]
        resp = _call_model(messages, model=model)

        # Step 3: tool calls
        for item in getattr(resp, "output", []):
            if getattr(item, "type", "") == "function_call":
                name = getattr(item, "name", "")
                try:
                    args = json.loads(item.arguments)
                except Exception:
                    args = {}
                print(f"[TOOL DEBUG] Function call: {name} with args {args}")
                if name == "build_plugin":
                    return builder.build_plugin(
                        plugin_name=args.get("plugin_name", ""),
                        purpose=args.get("purpose", "")
                    )
                elif name == "extend_plugin":
                    return extend_plugin.extend_plugin(
                        plugin_name=args.get("plugin_name", ""),
                        new_feature=args.get("new_feature", "")
                    )

        # Step 4: plain chat fallback
        out_text = getattr(resp, "output_text", None) or ""
        if not out_text:
            for item in resp.output:
                if getattr(item, "type", "") == "message":
                    for c in item.content:
                        if getattr(c, "type", "") == "output_text":
                            out_text = c.text or ""
                            break

        cm.record_assistant(plugin_name, out_text)
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

    except OpenAIError as e:
        err = {"status": "error", "error_type": "OpenAIError", "message": str(e)}
        print(f"[ERROR] {err}")
        return error_handler.attempt_repair(err, retries=2)

    except Exception as e:
        tb = traceback.format_exc()
        err = {"status": "error", "error_type": type(e).__name__, "message": str(e), "traceback": tb}
        print(f"[ERROR] {err}")
        return error_handler.attempt_repair(err, retries=2)
