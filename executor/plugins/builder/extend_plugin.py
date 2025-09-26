from __future__ import annotations
import json, os, re
from dataclasses import dataclass
from typing import List, Dict, Any

from executor.utils.plugin_resolver import resolve as resolve_plugin, PluginNotFound
from executor.connectors.openai_client import OpenAIClient
from executor.utils.error_handler import classify_error, ExecutorError
from executor.utils.patcher_utils import run_tests, WorkingDir
from executor.utils.self_repair import apply_file_edits
from executor.plugins.repo_analyzer import repo_analyzer

# NEW: import builder utilities for specialist scaffolding
from executor.plugins.builder import builder

@dataclass
class FileEdit:
    path: str
    content: str
    kind: str  # "code" | "test" | "doc"

# ---------------- Utilities ----------------

def _normalize_repo_map(repo_map: Dict[str, Any]) -> Dict[str, Any]:
    """Convert sets to lists so repo_map is JSON-serializable."""
    def convert(obj):
        if isinstance(obj, set):
            return list(obj)
        if isinstance(obj, dict):
            return {k: convert(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [convert(x) for x in obj]
        return obj
    return convert(repo_map)

def _parse_json_str(s: str) -> Dict[str, Any]:
    s = (s or "").strip()
    if not s:
        raise ExecutorError("empty_model_output", details={"why": "model returned empty"})
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"```json\s*(.*?)\s*```", s, re.DOTALL)
        if m: return json.loads(m.group(1))
        b, e = s.find("{"), s.rfind("}")
        if b != -1 and e != -1 and e > b: return json.loads(s[b:e+1])
        raise ExecutorError("malformed_response", details={"sample": s[:200]})

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

    # NEW: ensure specialist reference
    manifest["specialist"] = f"executor.plugins.{spec.name}.specialist"

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

def _ensure_specialist_exists(spec) -> None:
    """Guarantee specialist.py file exists for this plugin."""
    specialist_file = os.path.join(spec.dir_path, "specialist.py")
    if not os.path.exists(specialist_file):
        try:
            # Reuse builder template logic
            builder.main(spec.name, description=f"Specialist for {spec.name}")
        except Exception as e:
            print(f"[ExtendPlugin] Warning: failed to scaffold specialist for {spec.name}: {e}")

# ---------------- Main ----------------

def extend_plugin(plugin_identifier: str, user_goal: str, *, ci: bool = False) -> Dict[str, Any]:
    try:
        spec = resolve_plugin(plugin_identifier)
    except PluginNotFound as e:
        raise ExecutorError("plugin_not_found", details={"identifier": plugin_identifier, "why": str(e)})

    client = OpenAIClient()
    repo_map = _normalize_repo_map(repo_analyzer.scan_repo())

    attempts = 0
    max_attempts = 3
    last_report, proposal = None, None

    while attempts < max_attempts:
        attempts += 1
        try:
            if attempts == 1:
                data = _call_model_for_goal(client, spec, user_goal, repo_map)
            else:
                suspects = []
                if last_report:
                    suspects = _extract_suspects_from_traceback(last_report)
                if not suspects:
                    suspects = [spec.file_path]
                data = _call_model_for_repair(client, last_report, suspects, proposal or "Fix the errors.", repo_map)

            files = _materialize_files(spec, data)
            if not files:
                raise ExecutorError("model_error", details={"why": "no files generated"})

            success, result = _apply_and_test(spec, files, ci=ci)
            if success:
                # ✅ Ensure manifest & specialist are always present
                _update_manifest(spec, user_goal)
                _ensure_specialist_exists(spec)
                return {
                    "status": "ok",
                    "files": [f.path for f in files],
                    "changelog": data.get("changelog"),
                    "rationale": data.get("rationale"),
                }

            # failed tests
            err = ExecutorError("tests_failed", details={"report": result.report})
            classification = classify_error(err)
            proposal = classification.repair_proposal
            last_report = result.report

        except Exception as e:
            report = getattr(e, "details", None) or str(e)
            classification = classify_error(e if isinstance(e, ExecutorError) else ExecutorError("runtime_error", details={"report": str(e)}))
            proposal = getattr(classification, "repair_proposal", "Fix the errors.")
            last_report = report
            # loop continues until max_attempts

    return {"status": "failed", "report": last_report, "proposal": proposal}
