# executor/plugins/builder/extend_plugin.py
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
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

def _materialize_files(spec, data: Dict[str, Any]) -> List[FileEdit]:
    files = []
    for f in data.get("files", []):
        if not isinstance(f, dict): continue
        path, content = f.get("path"), f.get("content")
        kind = f.get("kind", "code")
        if path and content and str(content).strip():
            if not path.startswith("executor/") and not path.startswith("tests/"):
                if kind == "test" or os.path.basename(path).startswith("test_"):
                    path = os.path.join(spec.tests_dir, os.path.basename(path))
                else:
                    path = os.path.join(spec.dir_path, os.path.basename(path))
            files.append(FileEdit(path=path, content=content, kind=kind))
    return files

# ---------------- Model calls ----------------

def _call_model_for_goal(client: OpenAIClient, spec, goal: str, repo_map: Dict[str, Any]) -> Dict[str, Any]:
    system = (
        "You are extending a modular Python plugin.\n"
        "Preserve backward compatibility unless required.\n"
        "Generate minimal edits with tests.\n"
        "Respond ONLY with JSON: { rationale, changelog, files:[{path,content,kind}] }.\n"
    )
    prompt = (
        f"Goal: {goal}\n"
        f"Primary plugin file: {spec.file_path}\n"
        f"Tests dir: {spec.tests_dir}\n\n"
        f"Repo map:\n{json.dumps(repo_map, indent=2)}\n"
    )
    raw = client.generate_structured(system=system, user=prompt, attachments=[spec.file_path])
    return _parse_json_str(raw)

def _call_model_for_repair(client: OpenAIClient, report: str, suspect_files: List[str], proposal: str, repo_map: Dict[str, Any]) -> Dict[str, Any]:
    system = (
        "You are repairing a broken Python project.\n"
        "You will be given an error report, a repair proposal, a repo map, and suspect files.\n"
        "Respond ONLY with JSON: { rationale, changelog, files:[{path,content,kind}] }.\n"
        "- Fix the errors without breaking other code.\n"
        "- Do not reintroduce placeholders.\n"
        "- Keep changes minimal and targeted.\n"
    )
    user = f"Error report:\n{report}\n\nRepair proposal:\n{proposal}\n\nRepo map:\n{json.dumps(repo_map, indent=2)}\n"
    for path in suspect_files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                code = f.read()
            user += f"<FILE path='{path}'>\n{code}\n</FILE>\n"
        except Exception:
            continue
    raw = client.generate_structured(system=system, user=user, attachments=suspect_files)
    return _parse_json_str(raw)

# ---------------- Apply & test ----------------

def _apply_and_test(spec, files: List[FileEdit], *, ci: bool) -> tuple[bool, Any]:
    with WorkingDir(ci=ci) as wd:
        apply_file_edits(files, worktree=wd.path)
        result = run_tests(workdir=wd.path, select=[spec.tests_dir])
        if result.success:
            wd.commit_and_merge(message=f"Extend {spec.name}: apply edits")
        return result.success, result

# ---------------- Repo-aware error parsing ----------------

def _extract_suspects_from_traceback(report: str) -> List[str]:
    suspects = []
    for line in str(report).splitlines():
        m = re.search(r'File "(.+?)", line \d+', line)
        if m:
            path = m.group(1)
            if os.path.exists(path):
                suspects.append(path)
    return suspects

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
                _update_manifest(spec, user_goal)
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
            # Any error goes through repair loop
            report = getattr(e, "details", None) or str(e)
            classification = classify_error(e if isinstance(e, ExecutorError) else ExecutorError("runtime_error", details={"report": str(e)}))
            proposal = getattr(classification, "repair_proposal", "Fix the errors.")
            last_report = report
            # loop continues until max_attempts

    return {"status": "failed", "report": last_report, "proposal": proposal}
