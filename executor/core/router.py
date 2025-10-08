# executor/core/router.py
# PATCH START — LLM-driven intent router with registry fallback
from __future__ import annotations
import importlib, pkgutil, sys, traceback
from typing import Dict, Any, Callable

from executor.core.intent import infer_intent

# --- Optional: use your existing registry if available ---
def _load_registered_plugins_via_registry() -> Dict[str, Dict[str, Any]]:
    try:
        from executor.core import registry as reg  # type: ignore
        # Expect registry to provide: get_registered_plugins() -> Dict[str, Module]
        plugins = reg.get_registered_plugins()  # type: ignore
        out: Dict[str, Dict[str, Any]] = {}
        for name, mod in plugins.items():
            desc = ""
            try:
                if hasattr(mod, "describe_capabilities"):
                    desc = str(mod.describe_capabilities())  # type: ignore
            except Exception:
                desc = ""
            out[name] = {"module": mod, "description": desc}
        return out
    except Exception:
        return {}

# --- Fallback: dynamic loader scans executor.plugins.* ---
def _dynamic_scan_plugins() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    try:
        pkg_name = "executor.plugins"
        pkg = importlib.import_module(pkg_name)
        for modinfo in pkgutil.iter_modules(pkg.__path__, pkg_name + "."):
            try:
                mod = importlib.import_module(modinfo.name)
                # must expose can_handle() and handle()
                if hasattr(mod, "handle") and callable(getattr(mod, "handle")):
                    # name is leaf module path after executor.plugins.
                    leaf = modinfo.name.split(".")[-1]
                    desc = ""
                    if hasattr(mod, "describe_capabilities"):
                        try:
                            desc = str(mod.describe_capabilities())
                        except Exception:
                            desc = ""
                    out[leaf] = {"module": mod, "description": desc}
            except Exception:
                # keep scanning; avoid breaking on one bad plugin
                continue
    except Exception:
        pass
    return out

def _collect_plugins() -> Dict[str, Dict[str, Any]]:
    via_reg = _load_registered_plugins_via_registry()
    return via_reg if via_reg else _dynamic_scan_plugins()

def _call_plugin(mod, params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return mod.handle(params)  # plugin contract
    except Exception as e:
        return {
            "status": "error",
            "message": f"Plugin '{mod.__name__}' raised: {e}",
            "traceback": traceback.format_exc(),
        }

def route(user_text: str) -> Dict[str, Any]:
    """
    Public router API — maintained for backward compatibility.
    Returns a dict result from the chosen plugin, or a builder-ready plan.
    """
    plugins = _collect_plugins()
    # Shape for planner: {"name": {"description": "..."}}
    plan_plugins = {k: {"description": v.get("description", "")} for k, v in plugins.items()}

    plan = infer_intent(user_text, plan_plugins)
    target = plan.get("target_plugin") or "none"
    params = plan.get("parameters") or {}

    # If planner knows the plugin by a different alias, try fuzzy key match
    target_key = None
    if target in plugins:
        target_key = target
    else:
        # small, safe normalization
        t = target.replace("-", "_").lower()
        for k in plugins.keys():
            if k.replace("-", "_").lower() == t:
                target_key = k
                break

    if target_key:
        mod = plugins[target_key]["module"]
        result = _call_plugin(mod, params)
        # attach a small execution receipt
        result.setdefault("status", "ok")
        result.setdefault("meta", {})
        result["meta"].update({"intent": plan.get("intent"), "plugin": target_key})
        return result

    # No plugin matched — return a builder-ready response
    return {
        "status": "no_plugin",
        "message": "No existing plugin matched the request.",
        "plan": {
            "intent": plan.get("intent", "freeform.respond"),
            "suggested_plugin": plan.get("target_plugin", "new_plugin"),
            "parameters": params,
            "source_text": user_text,
        },
        "meta": {"plugins_available": list(plugins.keys())},
    }
# PATCH END