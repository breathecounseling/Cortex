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

# ---------------- Guardrails to prevent "green-on-stub" ----------------

def _is_trivial_code(content: str) -> bool:
    c = content or ""
    return ("def placeholder(" in c) or ("return 'stub'" in c) or ('return "stub"' in c)

def _is_trivial_test(content: str) -> bool:
    c = (content or "").replace(" ", "")
    # patterns like: assert plugin.placeholder()=='stub'
    return "placeholder()==" in c and ("=='stub'" in c or '=="stub"' in c)

def _collect_changed_files(files: List[FileEdit]) -> Tuple[List[FileEdit], List[FileEdit]]:
    code, tests = [], []
    for f in files:
        kind = (f.kind or "code").lower()
        if kind == "test" or os.path.basename(f.path).startswith("test_"):
            tests.append(f)
        else:
            code.append(f)
    return code, tests

def _require_nontrivial_changes(changed_code_files: List[FileEdit], changed_test_files: List[FileEdit]) -> Tuple[bool, str]:
    """
    Inspect the model-proposed edits. If they still look like placeholders or trivial tests,
    ask the caller to retry with a stricter prompt.
    """
    # If no code files were changed, that's suspicious for a build/extend goal
    if not changed_code_files:
        return False, "no_code_changes"

    # If any changed code still contains placeholders, reject
    for f in changed_code_files:
        if _is_trivial_code(f.content):
            return False, f"trivial_code:{os.path.basename(f.path)}"

    # If tests exist but remain trivial, reject
    for f in changed_test_files:
        if _is_trivial_test(f.content):
            return False, f"trivial_test:{os.path.basename(f.path)}"

    return True, "ok"

# ---------------- Core extend flow ----------------

def _call_model_for_edits(client: OpenAIClient, spec, user_goal: str, *, strict: bool) -> Dict[str, Any]:
    base_system = (
        "You are extending a modular Python plugin.\n"
        "Preserve backward compatibility unless the goal requires changes.\n"
        "Generate minimal edits with tests.\n"
        "Respond ONLY with JSON: { rationale, changelog, files:[{path,content,kind}] }.\n"
    )
    strict_addendum = (
        "\nHARD REQUIREMENTS:\n"
        "- Replace any 'placeholder' or 'return \"stub\"' code with real implementations.\n"
        "- Include at least one meaningful test that validates real behavior (NOT placeholder assertions).\n"
        "- If behavior is ambiguous, first write failing tests that encode the expected behavior from the goal; "
        "then implement code so those tests pass.\n"
        "- Do not output trivial tests like `assert plugin.placeholder() == 'stub'`.\n"
        "- Ensure paths are within the plugin or its tests directory.\n"
    )
    system = base_system + (strict_addendum if strict else "")
    prompt = (
        f"Goal: {user_goal}\n"
        f"Primary plugin file: {spec.file_path}\n"
        f"Tests directory: {spec.tests_dir}\n"
        "Return only JSON.\n"
    )
    raw = client.generate_structured(system=system, user=prompt, attachments=[spec.file_path])
    return _parse_json_str(raw)

def _materialize_files(spec, data: Dict[str, Any]) -> List[FileEdit]:
    files = []
    for f in data.get("files", []):
        if not isinstance(f, dict):
            continue
        path = f.get("path"); content = f.get("content"); kind = f.get("kind", "code")
        if path and content and str(content).strip():
            # Normalize destination: keep writes inside plugin dir or its tests dir
            if not path.startswith("executor/") and not path.startswith("tests/"):
                if kind == "test" or os.path.basename(path).startswith("test_"):
                    path = os.path.join(spec.tests_dir, os.path.basename(path))
                else:
                    path = os.path.join(spec.dir_path, os.path.basename(path))
            files.append(FileEdit(path=path, content=content, kind=kind))
    return files

def _apply_and_test(spec, files: List[FileEdit], *, ci: bool) -> Tuple[bool, Dict[str, Any]]:
    with WorkingDir(ci=ci) as wd:
        apply_file_edits(files, worktree=wd.path)
        test_result = run_tests(workdir=wd.path, select=[spec.tests_dir])
        if not test_result.success:
            err = ExecutorError("tests_failed", details={"report": test_result.report})
            classification = classify_error(err)
            return False, {"status": "tests_failed", "report": test_result.report, "proposal": classification.repair_proposal}
        wd.commit_and_merge(message=f"Extend {spec.name}: apply edits")
        return True, {}

def extend_plugin(plugin_identifier: str, user_goal: str, *, ci: bool = False) -> Dict[str, Any]:
    try:
        spec = resolve_plugin(plugin_identifier)
    except PluginNotFound as e:
        raise ExecutorError("plugin_not_found", details={"identifier": plugin_identifier, "why": str(e)})

    client = OpenAIClient()

    # ---------- First pass (normal prompt) ----------
    try:
        data = _call_model_for_edits(client, spec, user_goal, strict=False)
    except ExecutorError as e:
        classification = classify_error(e)
        return {"status": "model_error", "error": classification.name, "details": classification.details}

    files = _materialize_files(spec, data)
    if not files:
        return {"status": "model_error", "error": "empty_files", "details": {"raw": "no files in model output"}}

    code_files, test_files = _collect_changed_files(files)
    ok_nontrivial, reason = _require_nontrivial_changes(code_files, test_files)
    if not ok_nontrivial:
        # ---------- Second pass (strict prompt) ----------
        data2 = _call_model_for_edits(client, spec, user_goal, strict=True)
        files2 = _materialize_files(spec, data2)
        if not files2:
            return {"status": "model_error", "error": "empty_files_after_strict", "details": {"raw": "no files in strict output"}}
        code2, test2 = _collect_changed_files(files2)
        ok_nontrivial2, reason2 = _require_nontrivial_changes(code2, test2)
        if not ok_nontrivial2:
            return {
                "status": "tests_failed",
                "report": f"Edits remained trivial ({reason2}). Replace placeholders and write meaningful tests.",
                "proposal": "Regenerate implementation and tests without placeholder patterns."
            }
        files = files2
        data = data2

    # Apply files and run tests
    success, test_payload = _apply_and_test(spec, files, ci=ci)
    if not success:
        return test_payload

    # Update manifest on success
    _update_manifest(spec, user_goal)
    return {
        "status": "ok",
        "files": [e.path for e in files],
        "changelog": data.get("changelog"),
        "rationale": data.get("rationale"),
    }
