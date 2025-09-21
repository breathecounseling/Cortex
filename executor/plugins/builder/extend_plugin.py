# executor/plugins/extend_plugin.py
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

# JSON “contract” the model must follow.
MODEL_CONTRACT_HINT = (
    "Respond ONLY with a JSON object: { rationale, changelog, files }.\n"
    "files is an array of { path, content, kind }, where kind ∈ {'code','test','doc'}.\n"
    "Include at least one code file. Do not leave content empty."
)

def _parse_structured(payload: str) -> Dict[str, Any]:
    if not payload or not payload.strip():
        raise ExecutorError("empty_model_output", details={"why": "model returned empty string"})
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        # lenient fallback to ```json ... ``` fenced block
        import re
        m = re.search(r"```json\s*(.*?)\s*```", payload, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        # final: find first { ... }
        start = payload.find("{")
        end = payload.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(payload[start:end + 1])
        raise ExecutorError("malformed_response", details={"sample": payload[:300]})

def _normalize_paths(edits: List[FileEdit], plugin_dir: str, tests_dir: str) -> List[FileEdit]:
    normalized: List[FileEdit] = []
    for e in edits:
        p = e.path.strip()
        # route to plugin dir / tests dir when the path is bare
        if not p.startswith("executor/") and not p.startswith("tests/"):
            if e.kind == "test" or os.path.basename(p).startswith("test_"):
                p = os.path.join(tests_dir, os.path.basename(p))
            else:
                p = os.path.join(plugin_dir, os.path.basename(p))
        normalized.append(FileEdit(path=os.path.normpath(p), content=e.content, kind=e.kind))
    return normalized

def extend_plugin(plugin_identifier: str, user_goal: str, *, ci: bool = False) -> Dict[str, Any]:
    """
    Main entrypoint from REPL: extend an existing plugin by name/path.
    Returns a dict with status + details; never silently rolls back.
    """
    try:
        spec = resolve_plugin(plugin_identifier)
    except PluginNotFound as e:
        raise ExecutorError("plugin_not_found", details={"identifier": plugin_identifier, "why": str(e)})

    client = OpenAIClient()

    system = (
        "You are extending a modular Python plugin.\n"
        "Preserve backward compatibility unless the goal requires changes.\n"
        "Generate minimal, cohesive edits with tests.\n"
        + MODEL_CONTRACT_HINT
    )

    prompt = (
        f"Goal: {user_goal}\n"
        f"Primary plugin file: {spec.file_path}\n"
        f"Tests directory: {spec.tests_dir}\n"
        "If tests are missing, create pytest tests specific to this plugin.\n"
        "If you add new files, place plugin code inside the plugin directory and tests under the tests dir.\n"
    )

    # Attach current plugin file to give the model real context.
    attachments = [spec.file_path]

    try:
        raw = client.generate_structured(system=system, user=prompt, attachments=attachments)
        data = _parse_structured(raw)
    except ExecutorError as e:
        classification = classify_error(e)
        return {
            "status": "model_error",
            "error": classification.name,
            "details": classification.details,
            "proposal": classification.repair_proposal,
        }

    files_json = data.get("files", [])
    if not files_json:
        return {
            "status": "model_error",
            "error": "empty_files",
            "details": {"raw": (raw[:300] if isinstance(raw, str) else "<non-str>")},
            "proposal": "Retry with stronger constraint: at least one code file and one test file.",
        }

    # Coerce to FileEdit list
    edits: List[FileEdit] = []
    for f in files_json:
        if not isinstance(f, dict):
            continue
        path = f.get("path")
        content = f.get("content")
        kind = f.get("kind", "code")
        if not path or not isinstance(content, str) or content.strip() == "":
            continue
        edits.append(FileEdit(path=path, content=content, kind=kind))

    if not edits:
        return {
            "status": "model_error",
            "error": "filtered_empty_files",
            "details": {"reason": "files[] existed but had blank/invalid content"},
            "proposal": "Enforce non-empty file contents; regenerate.",
        }

    edits = _normalize_paths(edits, spec.dir_path, spec.tests_dir)

    # Apply & test within a temp working directory
    with WorkingDir(ci=ci) as wd:
        apply_file_edits(edits, worktree=wd.path)
        test_result = run_tests(workdir=wd.path, select=[spec.tests_dir])
        if not test_result.success:
            err = ExecutorError("tests_failed", details={"report": test_result.report, "paths": [e.path for e in edits]})
            classification = classify_error(err)
            return {
                "status": "tests_failed",
                "report": test_result.report,
                "proposal": classification.repair_proposal,
            }
        wd.commit_and_merge(message=f"Extend {spec.name}: {user_goal}")
        return {
            "status": "ok",
            "files": [e.path for e in edits],
            "changelog": data.get("changelog"),
            "rationale": data.get("rationale"),
        }
