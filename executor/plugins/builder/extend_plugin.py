# executor/plugins/builder/extend_plugin.py
from __future__ import annotations
import json
import os
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple

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

# ---------------- Utilities ----------------

def _parse_json_str(s: str) -> Dict[str, Any]:
    s = (s or "").strip()
    if not s:
        raise ExecutorError("empty_model_output", details={"why": "model returned empty"})
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        import re
        m = re.search(r"```json\s*(.*?)\s*```", s, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        b, e = s.find("{"), s.rfind("}")
        if b != -1 and e != -1 and e > b:
            return json.loads(s[b:e+1])
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
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

def _materialize_files(spec, data: Dict[str, Any]) -> List[FileEdit]:
    files = []
    for f in data.get("files", []):
        if not isinstance(f, dict):
            continue
        path = f.get("path"); content = f.get("content"); kind = f.get("kind", "code")
        if path and content and str(content).strip():
            if not path.startswith("executor/") and not path.startswith("tests/"):
                if kind == "test" or os.path.basename(path).startswith("test_"):
                    path = os.path.join(spec.tests_dir, os.path.basename(path))
                else:
                    path = os.path.join(spec.dir_path, os.path.basename(path))
            files.append(FileEdit(path=path, content=content, kind=kind))
    return files

# ---------------- Guardrails ----------------

def _is_trivial_code(content: str) -> bool:
    c = content or ""
    return ("def placeholder(" in c) or ("return 'stub'" in c) or ('return "stub"' in c)

def _is_trivial_test(content: str) -> bool:
    c = (content or "").replace(" ", "")
    return "placeholder()==" in c and ("=='stub'" in c or '==\"stub\"' in c)

def _require_nontrivial(files: List[FileEdit]) -> Tuple[bool, str]:
    if not files:
        return False, "no_files"
    for f in files:
        if f.kind == "code" and _is_trivial_code(f.content):
            return False, "trivial_code"
        if f.kind == "test" and _is_trivial_test(f.content):
            return False, "trivial_test"
    return True, "ok"

# ---------------- Model Calls ----------------

def _call_model_for_edits(client: OpenAIClient, spec, goal: str, *, strict: bool) -> Dict[str, Any]:
    base = (
        "You are extending a modular Python plugin.\n"
        "Preserve backward compatibility unless the goal requires changes.\n"
        "Generate minimal edits with tests.\n"
        "Respond ONLY with JSON: { rationale, changelog, files:[{path,content,kind}] }.\n"
    )
    strict_add = (
        "\nRequirements:\n"
        "- Remove any placeholder or stub code.\n"
        "- Implement real functionality.\n"
        "- Provide meaningful tests, not trivial ones.\n"
        "- If unclear, first write failing tests for expected behavior, then implement code.\n"
    )
    system = base + (strict_add if strict else "")
    prompt = (
        f"Goal: {goal}\n"
        f"Primary plugin file: {spec.file_path}\n"
        f"Tests directory: {spec.tests_dir}\n"
    )
    raw = client.generate_structured(system=system, user=prompt, attachments=[spec.file_path])
    return _parse_json_str(raw)

def _call_model_for_repair(client: OpenAIClient, broken_file: FileEdit, traceback: str) -> Dict[str, Any]:
    system = (
        "You are repairing a broken Python plugin file.\n"
        "You will be given the file content and a pytest traceback.\n"
        "Respond ONLY with JSON: { rationale, changelog, files:[{path,content,kind}] }.\n"
        "- Fix syntax errors or runtime errors.\n"
        "- Do not introduce placeholders.\n"
        "- Ensure the file is valid Python.\n"
    )
    user = (
        f"Traceback:\n{traceback}\n\n"
        f"File needing repair: {broken_file.path}\n"
        f"---\n{broken_file.content}\n---\n"
    )
    raw = client.generate_structured(system=system, user=user, attachments=[broken_file.path])
    return _parse_json_str(raw)

# ---------------- Apply + Test ----------------

def _apply_and_test(spec, files: List[FileEdit], *, ci: bool) -> Tuple[bool, Dict[str, Any], str]:
    with WorkingDir(ci=ci) as wd:
        apply_file_edits(files, worktree=wd.path)
        test_result = run_tests(workdir=wd.path, select=[spec.tests_dir])
        return test_result.success, {"report": test_result.report}, wd.path

# ---------------- Main ----------------

def extend_plugin(plugin_identifier: str, user_goal: str, *, ci: bool = False) -> Dict[str, Any]:
    try:
        spec = resolve_plugin(plugin_identifier)
    except PluginNotFound as e:
        raise ExecutorError("plugin_not_found", details={"identifier": plugin_identifier, "why": str(e)})

    client = OpenAIClient()

    # -------- First pass (normal prompt) --------
    try:
        data = _call_model_for_edits(client, spec, user_goal, strict=False)
    except ExecutorError as e:
        classification = classify_error(e)
        return {"status": "model_error", "error": classification.name, "details": classification.details}

    files = _materialize_files(spec, data)
    ok_nontrivial, reason = _require_nontrivial(files)
    if not ok_nontrivial:
        # Second pass with strict prompt
        data = _call_model_for_edits(client, spec, user_goal, strict=True)
        files = _materialize_files(spec, data)

    if not files:
        return {"status": "model_error", "error": "empty_files", "details": {}}

    # -------- Apply + Test --------
    success, payload, workdir = _apply_and_test(spec, files, ci=ci)
    if success:
        _update_manifest(spec, user_goal)
        return {
            "status": "ok",
            "files": [f.path for f in files],
            "changelog": data.get("changelog"),
            "rationale": data.get("rationale"),
        }

    # -------- Repair loop --------
    report = payload["report"]
    broken = [f for f in files if f.kind == "code"]
    if broken:
        try:
            repair_data = _call_model_for_repair(client, broken[0], report)
            repair_files = _materialize_files(spec, repair_data)
            if repair_files:
                success2, payload2, _ = _apply_and_test(spec, repair_files, ci=ci)
                if success2:
                    _update_manifest(spec, user_goal)
                    return {
                        "status": "ok",
                        "files": [f.path for f in repair_files],
                        "changelog": repair_data.get("changelog"),
                        "rationale": repair_data.get("rationale"),
                    }
                else:
                    return {"status": "tests_failed", "report": payload2["report"], "proposal": "manual repair needed"}
        except Exception as e:
            return {"status": "repair_failed", "error": str(e), "report": report}

    return {"status": "tests_failed", "report": report, "proposal": "manual repair needed"}
