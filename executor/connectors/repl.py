# executor/connectors/repl.py
from __future__ import annotations
import json
import os
import re
import sys
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone

from executor.connectors.openai_client import OpenAIClient
from executor.plugins.builder.extend_plugin import extend_plugin
from executor.utils.error_handler import ExecutorError, classify_error
from executor.utils.docket import Docket

# -----------------------------------------------------------------------------
# Memory bridges (conversation_manager if present, else fallback JSONL + JSON)
# -----------------------------------------------------------------------------
def _try_import_cm():
    try:
        from executor.plugins.conversation_manager.conversation_manager import (  # type: ignore
            save_turn as cm_save_turn,
            get_turns as cm_get_turns,
            load_facts as cm_load_facts,
            save_fact as cm_save_fact,
        )
        return cm_save_turn, cm_get_turns, cm_load_facts, cm_save_fact
    except Exception:
        return None, None, None, None

_CM_SAVE_TURN, _CM_GET_TURNS, _CM_LOAD_FACTS, _CM_SAVE_FACT = _try_import_cm()

_MEM_DIR = os.path.join(".executor", "memory")
os.makedirs(_MEM_DIR, exist_ok=True)

def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()

def _turns_path(session: str) -> str:
    return os.path.join(_MEM_DIR, f"{session}.jsonl")

def _facts_path(session: str) -> str:
    return os.path.join(_MEM_DIR, f"{session}_facts.json")

def _globals_path() -> str:
    return os.path.join(_MEM_DIR, "global_directives.json")

def _pending_confirm_path(session: str) -> str:
    return os.path.join(_MEM_DIR, f"{session}_pending_confirm.json")

def _save_turn_fallback(session: str, role: str, content: Any) -> None:
    rec = {"ts": _ts(), "role": role, "content": content}
    with open(_turns_path(session), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")

def _load_turns_fallback(session: str) -> List[Dict[str, str]]:
    p = _turns_path(session)
    if not os.path.exists(p):
        return []
    turns: List[Dict[str, str]] = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
                if rec.get("role") in {"user", "assistant", "system"}:
                    turns.append({"role": rec["role"], "content": rec["content"]})
            except Exception:
                continue
    return turns[-50:]

def _load_facts_fallback(session: str) -> Dict[str, Any]:
    p = _facts_path(session)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_fact_fallback(session: str, key: str, value: Any) -> None:
    data = _load_facts_fallback(session)
    data[key] = value
    with open(_facts_path(session), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def save_turn(session: str, role: str, content: Any) -> None:
    if _CM_SAVE_TURN:
        try: _CM_SAVE_TURN(session, role=role, content=content); return
        except Exception: pass
    _save_turn_fallback(session, role, content)

def get_turns(session: str) -> List[Dict[str, str]]:
    if _CM_GET_TURNS:
        try: return _CM_GET_TURNS(session)
        except Exception: pass
    return _load_turns_fallback(session)

def load_facts(session: str) -> Dict[str, Any]:
    if _CM_LOAD_FACTS:
        try: return _CM_LOAD_FACTS(session)  # type: ignore
        except Exception: pass
    return _load_facts_fallback(session)

def save_fact(session: str, key: str, value: Any) -> None:
    if _CM_SAVE_FACT:
        try: _CM_SAVE_FACT(session, key=key, value=value); return
        except Exception: pass
    _save_fact_fallback(session, key, value)

# -----------------------------------------------------------------------------
# Directives (persist across sessions) + Scope
# -----------------------------------------------------------------------------
_DEFAULT_DIRECTIVES: Dict[str, Any] = {
    "interaction_style": "chat-first",
    "clarification_mode": "one-at-a-time",  # "one-at-a-time" | "all-at-once"
    "memory_rule": "store all user inputs and assistant outputs incrementally",
    "facts_rule": "always extract/save stable facts from normal language",
    "task_rule": "collect prerequisites or subtasks in a docket",
    "action_rule": "act only after requirements are clarified",
    "error_rule": "never silently rollback; classify and propose a fix",
    "scope": None,  # optional string e.g. "nutrition_tracker"
}

def load_directives() -> Dict[str, Any]:
    p = _globals_path()
    data: Dict[str, Any] = {}
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    merged = dict(_DEFAULT_DIRECTIVES)
    merged.update(data or {})
    return merged

def save_directives(updates: Dict[str, Any]) -> None:
    p = _globals_path()
    current: Dict[str, Any] = {}
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                current = json.load(f)
        except Exception:
            current = {}
    current.update(updates or {})
    with open(p, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2)

# -----------------------------------------------------------------------------
# Repo scan (plugins and symbols) to detect reuse opportunities
# -----------------------------------------------------------------------------
def _index_repo_plugins() -> Dict[str, Dict[str, Any]]:
    """
    Return:
      { plugin_name: {
           "path": ".../executor/plugins/<name>",
           "symbols": set([...])   # function/class names discovered
        }, ... }
    """
    base = os.path.join("executor", "plugins")
    idx: Dict[str, Dict[str, Any]] = {}
    if not os.path.isdir(base):
        return idx
    for entry in os.listdir(base):
        plugin_dir = os.path.join(base, entry)
        if not os.path.isdir(plugin_dir):
            continue
        symbols = set()
        for root, _, files in os.walk(plugin_dir):
            for fn in files:
                if fn.endswith(".py"):
                    try:
                        with open(os.path.join(root, fn), "r", encoding="utf-8") as f:
                            src = f.read()
                        # crude symbol scrape (def/class names)
                        symbols.update(re.findall(r"def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", src))
                        symbols.update(re.findall(r"class\s+([A-Za-z_][A-Za-z0-9_]*)\s*[\(:]", src))
                    except Exception:
                        pass
        idx[entry] = {"path": plugin_dir, "symbols": symbols}
    return idx

def _plugin_exists(name: str, idx: Optional[Dict[str, Dict[str, Any]]] = None) -> bool:
    idx = idx or _index_repo_plugins()
    return name in idx

def _find_symbol_owner(symbol: str, idx: Optional[Dict[str, Dict[str, Any]]] = None) -> Optional[str]:
    idx = idx or _index_repo_plugins()
    s_lower = symbol.lower()
    for plugin, meta in idx.items():
        for sym in meta["symbols"]:
            if sym.lower() == s_lower:
                return plugin
    return None

# -----------------------------------------------------------------------------
# Orchestrator prompt & structure contract (chat-first, infer facts/tasks, act)
# -----------------------------------------------------------------------------
STRUCTURE_INSTRUCTION = (
    "You are the Cortex Executor Orchestrator.\n"
    "Behaviors (MUST FOLLOW):\n"
    "1) Chat-first: speak conversationally. Keep replies clear and compact. Respect 'scope' if set.\n"
    "2) Clarifications: when missing info, ask per 'clarification_mode'.\n"
    "   - 'one-at-a-time': ask ONE essential question.\n"
    "   - 'all-at-once': ask a concise checklist.\n"
    "3) Facts: ALWAYS extract stable facts from normal language (no special phrasing needed).\n"
    "   Example: 'I want to build a nutrition tracker' -> facts_to_save includes {\"key\":\"project\",\"value\":\"nutrition tracker\"}.\n"
    "4) Tasks: ALWAYS add missing prerequisites/subtasks to 'tasks_to_add'.\n"
    "5) Actions: Propose concrete actions ONLY when enough info is gathered. Do not include types; host decides build vs extend.\n"
    "6) Errors: never silently rollback; summarize the error cause and suggest a fix.\n"
    "7) Directive updates: if user changes behavior (e.g. 'ask all questions at once'), include 'directive_updates'.\n"
    "8) Scope management: if user says 'focus on X', include 'directive_updates': {\"scope\":\"X\"}.\n"
    "Return ONLY JSON with shape:\n"
    "{\n"
    '  "assistant_message": string,\n'
    '  "mode": "ask" | "act" | "respond",\n'
    '  "questions": [string],\n'
    '  "facts_to_save": [{"key": string, "value": any}],\n'
    '  "tasks_to_add": [{"title": string, "priority": "low"|"normal"|"high"}],\n'
    '  "directive_updates": {"clarification_mode": "one-at-a-time"|"all-at-once", "scope": string, ...},\n'
    '  "actions": [ {"plugin": string, "goal": string} ]\n'
    "}\n"
    "If unsure, prefer mode='ask'. Never emit empty JSON. Never include prose outside JSON."
)

SESSION = "repl"
BANNER = "Executor — chat naturally. I’ll remember, ask clarifying questions, and act when ready. Type 'quit' to exit."

def _parse_json(s: str) -> Dict[str, Any]:
    s = (s or "").strip()
    if not s:
        return {}
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        import re
        m = re.search(r"```json\s*(.*?)\s*```", s, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        b = s.find("{"); e = s.rfind("}")
        if b != -1 and e != -1 and e > b:
            return json.loads(s[b:e+1])
        return {}

def _friendly_error(detail: str) -> str:
    # Translate common issues to friendly guidance
    if "ModuleNotFoundError: No module named 'executor'" in detail:
        return "Tests couldn't import the 'executor' package. We'll set PYTHONPATH when running pytest."
    if "No module named 'executor.plugins.extend_plugin'" in detail:
        return "An import is pointing to executor.plugins.extend_plugin, but extend_plugin lives under builder/ now."
    if "plugin_not_found" in detail:
        return "The requested plugin wasn't found. We can create it or reuse an existing one with similar functionality."
    return "Something failed during execution. I proposed a fix and can try again after adjustments."

def _build_messages(user_text: str, docket: Docket, directives: Dict[str, Any]) -> List[Dict[str, str]]:
    facts = load_facts(SESSION)
    turns = get_turns(SESSION)
    sys_base = {
        "role": "system",
        "content": "You are a proactive architect for the Cortex Executor. Follow directives strictly."
    }
    sys_directives = {"role": "system", "content": f"Current directives: {json.dumps(directives)}"}
    sys_facts = {"role": "system", "content": f"Known facts: {json.dumps(facts)}"}
    sys_docket = {"role": "system", "content": f"Current docket: {json.dumps(docket.list_tasks())}"}
    sys_contract = {"role": "system", "content": STRUCTURE_INSTRUCTION}
    msgs: List[Dict[str, str]] = [sys_base, sys_directives, sys_facts, sys_docket]
    # honor scope by including a reminder system message
    if directives.get("scope"):
        msgs.append({"role": "system", "content": f"Stay focused on scope: {directives['scope']}"})
    msgs.extend(turns[-20:])
    msgs.append({"role": "user", "content": user_text})
    msgs.append(sys_contract)
    return msgs

# Pending confirmation store (e.g., “build ui_builder?”)
def _load_pending_confirm(session: str) -> Optional[Dict[str, Any]]:
    p = _pending_confirm_path(session)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _save_pending_confirm(session: str, obj: Optional[Dict[str, Any]]) -> None:
    p = _pending_confirm_path(session)
    if obj is None:
        if os.path.exists(p):
            try: os.remove(p)
            except Exception: pass
        return
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)

def _interpret_confirmation(user_text: str) -> Optional[bool | str]:
    """
    Returns:
      True  -> confirmed yes
      False -> explicit no
      str   -> a different plugin name provided
      None  -> not a confirmation response
    """
    t = user_text.strip().lower()
    if t in {"yes", "y", "ok", "do it", "sure", "confirm"}:
        return True
    if t in {"no", "n", "stop", "cancel"}:
        return False
    # If they typed a single token (likely a plugin name), accept it as rename
    if len(t.split()) == 1 and re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", t):
        return t
    return None

def _handle_actions(actions: List[Dict[str, Any]], user_text: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Execute actions with auto-detect build/extend + confirmation + reuse suggestion via repo scan.
    Returns (results, optional_confirmation_message)
    """
    results: List[Dict[str, Any]] = []
    idx = _index_repo_plugins()

    # Check if we are answering a pending confirmation
    pending = _load_pending_confirm(SESSION)
    if pending:
        interp = _interpret_confirmation(user_text)
        if interp is True:
            # proceed to scaffold new plugin
            try:
                from executor.plugins.builder.builder import main as build_plugin
                build_plugin(pending["plugin"], pending.get("goal") or "")
                results.append({"type": "build", "status": "ok", "plugin": pending["plugin"]})
                _save_pending_confirm(SESSION, None)
            except Exception as e:
                results.append({"type": "build", "status": "error", "error": f"{type(e).__name__}: {e}"})
            return results, None
        elif interp is False:
            _save_pending_confirm(SESSION, None)
            results.append({"type": "build", "status": "cancelled"})
            return results, None
        elif isinstance(interp, str):
            # treat as rename
            pending["plugin"] = interp
            _save_pending_confirm(SESSION, pending)
            return results, f"Renamed to '{interp}'. Confirm scaffolding this new plugin? (yes/no)"
        else:
            # pending but not answered; we will re-ask after processing below
            pass

    # Process fresh actions
    for act in actions or []:
        plugin = (act.get("plugin") or "").strip()
        goal = (act.get("goal") or "").strip()
        if not plugin:
            results.append({"status": "error", "msg": "missing plugin name"})
            continue

        # If plugin exists -> extend
        if _plugin_exists(plugin, idx):
            try:
                res = extend_plugin(plugin, goal)
                if res.get("status") != "ok":
                    # user-friendly explanation
                    rep = res.get("report") or json.dumps(res)
                    results.append({
                        "type": "extend",
                        "status": "error",
                        "friendly": _friendly_error(rep),
                        "result": res
                    })
                else:
                    results.append({"type": "extend", "status": "ok", "result": res})
            except ExecutorError as e:
                results.append({"type": "extend", "status": "error", "error": classify_error(e).__dict__})
            except Exception as e:
                results.append({"type": "extend", "status": "error", "error": f"{type(e).__name__}: {e}"})
            continue

        # If plugin missing, try to find similar functionality (symbol match)
        owner = _find_symbol_owner(plugin, idx)  # if they referenced a feature instead of plugin
        if owner:
            msg = (
                f"⚠️ It looks like '{plugin}' already exists as a symbol in the '{owner}' plugin. "
                f"Do you want me to extend '{owner}' instead, or scaffold a new plugin named '{plugin}'?"
                " Reply 'extend owner', 'yes' to build new, a new name, or 'no'."
            )
            results.append({"type": "confirm_reuse", "message": msg, "plugin": owner, "symbol": plugin})
            # store pending as a potential build if they insist
            _save_pending_confirm(SESSION, {"plugin": plugin, "goal": goal})
            return results, msg

        # Otherwise confirm scaffolding a new plugin
        confirm = (
            f"⚠️ Plugin '{plugin}' not found under executor/plugins. "
            f"Do you want me to scaffold a NEW plugin named '{plugin}' for: {goal}? "
            "Reply 'yes' to proceed, provide a different name, or 'no' to cancel."
        )
        results.append({"type": "confirm_build", "plugin": plugin, "goal": goal, "message": confirm})
        _save_pending_confirm(SESSION, {"plugin": plugin, "goal": goal})
        return results, confirm

    return results, None

# -----------------------------------------------------------------------------
# Main REPL loop
# -----------------------------------------------------------------------------
def main():
    print(BANNER)
    client = OpenAIClient()
    docket = Docket(namespace=SESSION)
    directives = load_directives()

    for raw in sys.stdin:
        user_text = raw.strip()
        if not user_text:
            continue
        if user_text.lower() in {"quit", "exit"}:
            print("bye")
            return

        # Messages for the model
        msgs = _build_messages(user_text, docket, directives)

        try:
            raw_out = client.chat(msgs, response_format={"type": "json_object"})
        except Exception as e:
            print(f"[transport error] {type(e).__name__}: {e}")
            continue

        data = _parse_json(raw_out)
        if not data or "assistant_message" not in data:
            # Fallback: ask for rephrase
            print("I couldn’t parse a plan. Could you rephrase?")
            save_turn(SESSION, "user", user_text)
            save_turn(SESSION, "assistant", "I couldn’t parse a plan. Could you rephrase?")
            continue

        # 1) Persist directive updates (includes scope changes)
        if data.get("directive_updates"):
            try:
                save_directives(data["directive_updates"])
                directives = load_directives()
            except Exception:
                pass

        # 2) Persist facts
        for f in data.get("facts_to_save") or []:
            k, v = f.get("key"), f.get("value")
            if k:
                save_fact(SESSION, k, v)

        # 3) Docket tasks
        for t in data.get("tasks_to_add") or []:
            title = t.get("title")
            prio = (t.get("priority") or "normal").lower()
            if title:
                docket.add(title=title, priority=prio)

        # 4) Speak to the user
        assistant_msg = data.get("assistant_message") or ""
        if assistant_msg:
            print(assistant_msg)

        # 5) Act if requested (auto-detect build/extend + confirmation + reuse)
        confirmation_note: Optional[str] = None
        if data.get("mode") == "act":
            results, confirmation_note = _handle_actions(data.get("actions") or [], user_text)
            summary = {
                "actions_ran": results,
                "docket": docket.list_tasks(),
                "scope": directives.get("scope"),
            }
            # Session summary (EXTRA #1)
            summary_text = json.dumps(summary, indent=2)
            print(summary_text)
            # Feedback loop (EXTRA #4)
            print("Did this move things in the right direction? (yes/no or specify adjustments)")

            # Save compact history
            save_turn(SESSION, "assistant", f"{assistant_msg}\n{summary_text}")
            save_turn(SESSION, "user", user_text)
            continue

        # If mode=ask/respond: just persist the conversation
        save_turn(SESSION, "assistant", assistant_msg)
        save_turn(SESSION, "user", user_text)

        # If there is a pending confirmation, gently remind (EXTRA #2 scoped mode already honored above)
        if confirmation_note:
            print(confirmation_note)

if __name__ == "__main__":
    main()