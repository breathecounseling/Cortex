# executor/utils/plugin_resolver.py
from __future__ import annotations
import os
import re
import glob
from dataclasses import dataclass
from typing import Optional, List

PLUGIN_ROOT = os.path.join("executor", "plugins")

@dataclass
class PluginSpec:
    name: str               # canonical snake_case plugin name, e.g., "conversation_manager"
    dir_path: str           # executor/plugins/conversation_manager
    module_path: str        # executor.plugins.conversation_manager.conversation_manager
    file_path: str          # executor/plugins/conversation_manager/conversation_manager.py
    tests_dir: str          # tests/plugins/conversation_manager

class PluginNotFound(Exception):
    pass

def _snake(s: str) -> str:
    s = s.replace("-", "_").replace(" ", "_")
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", s)
    return s.lower().strip("_")

def _candidate_dirs() -> List[str]:
    if not os.path.isdir(PLUGIN_ROOT):
        return []
    return [p for p in glob.glob(os.path.join(PLUGIN_ROOT, "*")) if os.path.isdir(p)]

def _is_plugin_dir(path: str) -> bool:
    if not os.path.isdir(path):
        return False
    files = os.listdir(path)
    has_init = "__init__.py" in files
    has_py = any(f.endswith(".py") and f != "__init__.py" for f in files)
    return has_init or has_py

def _detect_primary_file(dir_path: str) -> Optional[str]:
    """Prefer {dirname}.py, else first non-init .py, else __init__.py."""
    basename = os.path.basename(dir_path)
    preferred = os.path.join(dir_path, f"{basename}.py")
    if os.path.isfile(preferred):
        return preferred
    for f in sorted(os.listdir(dir_path)):
        if f.endswith(".py") and f != "__init__.py":
            return os.path.join(dir_path, f)
    initp = os.path.join(dir_path, "__init__.py")
    return initp if os.path.isfile(initp) else None

def resolve(identifier: str) -> PluginSpec:
    """
    Accepts:
      - "conversation_manager"
      - "executor/plugins/conversation_manager"
      - "executor/plugins/conversation_manager/conversation_manager.py"
      - "executor.plugins.conversation_manager" (module-ish)
    Returns PluginSpec or raises PluginNotFound.
    """
    if not identifier:
        raise PluginNotFound("Empty plugin identifier")

    if identifier.endswith(".py") and os.path.isfile(identifier):
        file_path = os.path.normpath(identifier)
        dir_path = os.path.dirname(file_path)
        name = _snake(os.path.splitext(os.path.basename(file_path))[0])
    elif os.path.isdir(identifier):
        dir_path = os.path.normpath(identifier)
        name = _snake(os.path.basename(dir_path))
        file_path = _detect_primary_file(dir_path) or ""
    elif identifier.startswith("executor.plugins."):
        parts = identifier.split(".")
        name = _snake(parts[-1])
        dir_path = os.path.join(PLUGIN_ROOT, name)
        file_path = _detect_primary_file(dir_path) or ""
    else:
        name = _snake(identifier)
        dir_path = os.path.join(PLUGIN_ROOT, name)
        if not os.path.isdir(dir_path):
            candidates = [d for d in _candidate_dirs() if name in os.path.basename(d).lower()]
            if len(candidates) == 1:
                dir_path = candidates[0]
                name = os.path.basename(dir_path)
            elif len(candidates) > 1:
                candidates.sort(key=lambda p: len(os.path.basename(p)))
                dir_path = candidates[0]
                name = os.path.basename(dir_path)
            else:
                raise PluginNotFound(f"Plugin directory not found for '{identifier}' under {PLUGIN_ROOT}")
        file_path = _detect_primary_file(dir_path) or ""

    if not dir_path or not _is_plugin_dir(dir_path):
        raise PluginNotFound(f"'{identifier}' does not point to a valid plugin directory")

    if not file_path or not os.path.isfile(file_path):
        raise PluginNotFound(
            f"Plugin '{identifier}' resolved to '{dir_path}', but no primary .py file was found"
        )

    # Make module_path point to the primary file (even if __init__.py)
    module_path = file_path.replace(os.sep, ".").removesuffix(".py")
    tests_dir = os.path.join("tests", "plugins", name)

    return PluginSpec(
        name=name,
        dir_path=dir_path,
        module_path=module_path,
        file_path=file_path,
        tests_dir=tests_dir,
    )