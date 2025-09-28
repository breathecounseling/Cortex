from __future__ import annotations
import os
import json
from typing import Any, Dict


def _ensure_parent_packages_exist(base_dir: str) -> None:
    """
    Ensure tmp scaffolds have package inits:
      <base_dir>/executor/__init__.py
      <base_dir>/executor/plugins/__init__.py
    """
    exec_dir = os.path.join(base_dir, "executor")
    plugins_dir = os.path.join(exec_dir, "plugins")
    os.makedirs(plugins_dir, exist_ok=True)
    for path in (os.path.join(exec_dir, "__init__.py"),
                 os.path.join(plugins_dir, "__init__.py")):
        if not os.path.exists(path):
            open(path, "w").close()


def _write_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _write_specialist_from_template_or_fallback(plugin_name: str, plugin_dir: str) -> None:
    """
    Create specialist.py from templates/specialist.py.j2 if present,
    otherwise write a minimal fallback specialist that satisfies the tests.
    """
    spec_file = os.path.join(plugin_dir, "specialist.py")
    if os.path.exists(spec_file):
        return

    # Try the template (repo path: executor/plugins/templates/specialist.py.j2)
    template_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "templates", "specialist.py.j2")
    )
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as tf:
            tmpl = tf.read()
        with open(spec_file, "w", encoding="utf-8") as sf:
            sf.write(tmpl.replace("{{ plugin_name }}", plugin_name))
        return

    # Fallback: minimal working specialist
    fallback = f'''"""
Auto-generated specialist for {plugin_name}.
"""
from typing import Dict, Any

def describe_capabilities():
    return ["scaffolded"]

def can_handle(goal: str) -> bool:
    return isinstance(goal, str) and len(goal) > 0

def handle(intent: Dict[str, Any]) -> Dict[str, Any]:
    goal = intent.get("goal", "")
    return {{"status": "ok", "message": f"{plugin_name} handled: " + str(goal)}}
'''
    with open(spec_file, "w", encoding="utf-8") as sf:
        sf.write(fallback)


def main(plugin_name: str, description: str | None = None) -> None:
    """
    Tests call this as: builder.main(name, "Some description")
    So the second arg is a STRING, not a dict.
    """
    cwd = os.getcwd()
    _ensure_parent_packages_exist(cwd)

    base = os.path.join("executor", "plugins", plugin_name)
    os.makedirs(base, exist_ok=True)

    # ensure plugin package
    init_py = os.path.join(base, "__init__.py")
    if not os.path.exists(init_py):
        open(init_py, "w").close()

    # build manifest dict explicitly (do NOT do dict(description) etc.)
    manifest = {
        "name": plugin_name,
        "description": description or f"Plugin {plugin_name}",
        "capabilities": [],
        "specialist": f"executor.plugins.{plugin_name}.specialist",
    }

    # write plugin.json (primary for tests) and manifest.json (compat)
    _write_json(os.path.join(base, "plugin.json"), manifest)
    _write_json(os.path.join(base, "manifest.json"), manifest)

    # specialist.py
    _write_specialist_from_template_or_fallback(plugin_name, base)

    print(f"✅ Created new plugin: {plugin_name}")
