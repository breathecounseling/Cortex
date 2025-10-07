from __future__ import annotations
from typing import List, Dict

HEADER = (
    "You are Cortex's Self-Healer. Follow the Patch Generation Protocol strictly.\n"
    "Output only complete drop-in replacements inside fenced code blocks using:\n"
    "```patch:<repo-relative-path>\n<full file content>\n```\n"
    "Never include partial diffs; always output full file content."
)


def build_messages(failure_cluster: List[Dict[str, str]], repo_outline: str) -> List[Dict[str, str]]:
    """Builds the system + user messages for LLM chat requests."""
    sys_msg = {"role": "system", "content": HEADER}

    user_lines = ["Repository Outline:", repo_outline, "\nFailures to fix:"]
    for f in failure_cluster:
        user_lines.append(
            f"- {f['file']}:{f.get('line', '?')} in {f['classname']}::{f['testname']}\n"
            f"Message: {f['message']}\nTraceback:\n{f['traceback']}"
        )

    user_msg = {"role": "user", "content": "\n".join(user_lines)}
    return [sys_msg, user_msg]