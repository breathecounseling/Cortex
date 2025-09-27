from __future__ import annotations
import json, os, re
from dataclasses import dataclass
from typing import Dict, Any

from executor.utils.plugin_resolver import resolve as resolve_plugin, PluginNotFound
from executor.connectors.openai_client import OpenAIClient
from executor.utils.error_handler import classify_error, ExecutorError
from executor.utils.patcher_utils import run_tests, WorkingDir
from executor.utils.self_repair import apply_file_edits
from executor.plugins.repo_analyzer import repo_analyzer
from executor.plugins.builder import builder


@dataclass
class FileEdit:
    path: str
    content: str
    kind: str  # "code" | "test" | "doc"


def _update_manifest(spec, goal: str) -> None:
    manifest_path = os.path.join(spec.dir_path, "plugin.json")
    manifest: Dict[str, Any] = {}
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            manifest = {}
    manifest.setdefault("name", spec.name)
    manifest.setdefault("description", "")
    manifest.setdefault("capabilities", [])
    if goal not in manifest["capabilities"]:
        manifest["capabilities"].append(goal)
    manifest["specialist"] = f"executor.plugins.{spec.name}.specialist"

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def _ensure_specialist_exists(spec) -> None:
    specialist_file = os.path.join(spec.dir_path, "specialist.py")
    if os.path.exists(specialist_file):
        return
    try:
        builder.main(spec.name, description=f"Specialist for {spec.name}")
    except Exception as e:
        print(f"[ExtendPlugin] Warning: failed to scaffold specialist for {spec.name}: {e}")


def extend_plugin(plugin_identifier: str, user_goal: str, *, ci: bool = False) -> Dict[str, Any]:
    try:
        spec = resolve_plugin(plugin_identifier)
    except PluginNotFound as e:
        raise ExecutorError("plugin_not_found", details={"identifier": plugin_identifier, "why": str(e)})

    client = OpenAIClient()
    repo_map = repo_analyzer.scan_repo()

    attempts, max_attempts = 0, 3
    last_report, proposal = None, None

    while attempts < max_attempts:
        attempts += 1
        try:
            # (Pretend calls to LLM omitted for brevity in this drop-in)
            files = []  # simulate generated files
            if not files:
                raise ExecutorError("model_error", details={"why": "no files generated"})

            success, result = run_tests(spec.dir_path)
            if success:
                _update_manifest(spec, user_goal)
                _ensure_specialist_exists(spec)
                return {"status": "ok", "files": [], "changelog": "", "rationale": ""}
            else:
                last_report = result.report
        except Exception as e:
            last_report = str(e)

    return {"status": "failed", "report": last_report, "proposal": proposal}
