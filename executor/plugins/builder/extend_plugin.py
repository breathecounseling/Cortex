# executor/plugins/builder/extend_plugin.py
from __future__ import annotations
import json
import os
from dataclasses import dataclass
from typing import List, Dict, Any

from executor.utils.plugin_resolver import resolve as resolve_plugin, PluginNotFound
from executor.connectors.openai_client import OpenAIClient
from executor.utils.error_handler import classify_error, ExecutorError
from executor.utils.patcher_utils import run_tests, WorkingDir
from executor.utils.self_repair import apply_file_edits

@dataclass
class FileEdit:
    path: str
    content: str
    kind: str  # "code" | "test" | "doc"

def _parse_json_str(s: str) -> Dict[str, Any]:
    s = (s or "").strip()
    if not s:
        raise ExecutorError("empty_model_output", details={"why": "model returned empty"})
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        import re
        m = re.search(r"```json\\s*(.*?)\\s*```", s, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        b, e = s.find("{"), s.rfind("}")
        if b != -1 and e != -1 and e > b:
            return json.loads(s[b:e+1])
        raise ExecutorError("malformed_response", details={"sample": s[:200]})

def _update_manifest(spec, goal: str) -> None:
    """
    Update plugin.json capabilities with the new goal.
    """
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
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

def extend_plugin(plugin_identifier: str, user_goal: str, *, ci: bool = False) -> Dict[str, Any]:
    try:
        spec = resolve_plugin(plugin_identifier)
    except PluginNotFound as e:
        raise ExecutorError("plugin_not_found", details={"identifier": plugin_identifier, "why": str(e)})

    client = OpenAIClient()
    system = (
        "You are extending a modular Python plugin.\n"
        "Preserve backward compatibility unless the goal requires changes.\n"
        "Generate minimal edits with tests.\n"
        "Respond ONLY with JSON: { rationale, changelog, files:[{path,content,kind}] }.\n"
    )
    prompt = (
        f"Goal: {user_goal}\n"
        f"Primary plugin file: {spec.file_path}\n"
        f"Tests directory: {spec.tests_dir}\n"
    )

    raw = client.generate_structured(system=system, user=prompt, attachments=[spec.file_path])
    try:
        data = _parse_json_str(raw)
    except ExecutorError as e:
        classification = classify_error(e)
        return {"status": "model_error", "error": classification.name, "details": classification.details}

    files = []
    for f in data.get("files", []):
        if not isinstance(f, dict):
            continue
        path = f.get("path"); content = f.get("content")
        kind = f.get("kind", "code")
        if path and content and content.strip():
            if not path.startswith("executor/") and not path.startswith("tests/"):
                if kind == "test" or os.path.basename(path).startswith("test_"):
                    path = os.path.join(spec.tests_dir, os.path.basename(path))
                else:
                    path = os.path.join(spec.dir_path, os.path.basename(path))
            files.append(FileEdit(path=path, content=content, kind=kind))

    if not files:
        return {"status": "model_error", "error": "empty_files", "details": {"raw": raw[:200]}}

    with WorkingDir(ci=ci) as wd:
        apply_file_edits(files, worktree=wd.path)
        test_result = run_tests(workdir=wd.path, select=[spec.tests_dir])
        if not test_result.success:
            err = ExecutorError("tests_failed", details={"report": test_result.report})
            classification = classify_error(err)
            return {"status": "tests_failed", "report": test_result.report, "proposal": classification.repair_proposal}
        wd.commit_and_merge(message=f"Extend {spec.name}: {user_goal}")
        # update manifest after success
        _update_manifest(spec, user_goal)
        return {
            "status": "ok",
            "files": [e.path for e in files],
            "changelog": data.get("changelog"),
            "rationale": data.get("rationale"),
        }