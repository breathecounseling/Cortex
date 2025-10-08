# executor/core/intent.py
# LLM-driven intent inference for Cortex router.
from __future__ import annotations
import os, json
from typing import Dict, Any, List, Optional

try:
    # Prefer Responses API if you're already using it elsewhere
    from openai import OpenAI
    _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    _use_responses = True
except Exception:
    _client = None
    _use_responses = False

INTENT_MODEL = os.getenv("CORTEX_INTENT_MODEL") or os.getenv("ROUTER_MODEL") or os.getenv("DEFAULT_MODEL") or "gpt-4o"
INTENT_SYSTEM = (
    "You are Cortex's Task Planner. Given a user message and a list of available plugins, "
    "produce a compact JSON plan with keys: intent, target_plugin, parameters.\n"
    "Rules:\n"
    "- intent: a concise verb-noun (e.g., 'search.web', 'weather.query', 'planner.create')\n"
    "- target_plugin: EXACT module name from the provided list, or 'none' if no match\n"
    "- parameters: a JSON object with fields the plugin will need (never empty if you can infer anything)\n"
    "- If no plugin fits, set target_plugin='none' and make parameters helpful for a builder to scaffold.\n"
)

def _format_plugins_for_prompt(plugins: Dict[str, Dict[str, str]]) -> str:
    # plugins: {"search": {"description": "..."}}
    lines = []
    for name, meta in plugins.items():
        desc = meta.get("description") or ""
        lines.append(f"- {name}: {desc}")
    return "\n".join(lines) if lines else "(no plugins registered)"

def _call_llm(prompt: str) -> str:
    if _use_responses:
        resp = _client.responses.create(model=INTENT_MODEL, input=prompt)
        return resp.output_text
    # Fallback to Chat Completions if Responses isn’t available
    from openai import ChatCompletion, OpenAIError  # type: ignore
    try:
        cc = ChatCompletion.create(
            model=INTENT_MODEL,
            messages=[{"role": "system", "content": INTENT_SYSTEM}, {"role": "user", "content": prompt}],
        )
        return cc.choices[0].message.content or "{}"
    except Exception as e:
        return "{}"

def infer_intent(message: str, available_plugins: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    """
    available_plugins: {"search": {"description": "..."}}
    Returns plan dict: {"intent": "...", "target_plugin": "...", "parameters": {...}}
    """
    catalog = _format_plugins_for_prompt(available_plugins)
    user = message.strip()
    user = user.replace("\n", " ").strip()
    prompt = (
        f"{INTENT_SYSTEM}\n\n"
        f"Available plugins:\n{catalog}\n\n"
        f"User message: \"{user}\"\n\n"
        f"Return ONLY JSON (no prose), e.g. {{\"intent\": \"search.web\", \"target_plugin\": \"search\", \"parameters\": {{\"query\": \"...\"}}}}"
    )
    raw = _call_llm(prompt).strip()
    # be defensive parsing
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {"intent": "freeform.respond", "target_plugin": "none", "parameters": {"text": message}}
    try:
        data = json.loads(raw[start:end+1])
        if not isinstance(data, dict): raise ValueError("not dict")
        intent = str(data.get("intent") or "freeform.respond")
        target = str(data.get("target_plugin") or "none")
        params = data.get("parameters") or {}
        if not isinstance(params, dict): params = {"raw": str(params)}
        return {"intent": intent, "target_plugin": target, "parameters": params}
    except Exception:
        return {"intent": "freeform.respond", "target_plugin": "none", "parameters": {"text": message}}