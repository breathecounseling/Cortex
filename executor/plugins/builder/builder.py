"""
Builder Plugin with Autotester + Patcher + Git Integration
"""

import os
import subprocess
import json
import shutil
from executor.connectors import openai_client  # to call GPT-5 for patching

PLUGIN_BASE = os.path.join(os.path.dirname(__file__), "..")

def run_pytest(test_file: str):
    """Run pytest on a single file, return (passed, output)."""
    try:
        result = subprocess.run(
            ["pytest", "-q", test_file],
            capture_output=True,
            text=True,
            check=True
        )
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, e.stdout + "\n" + e.stderr

def request_patch(plugin_name: str, code: str, test_code: str, error_log: str):
    """Ask GPT-5 (Responses API) to patch code based on failing tests."""
    prompt = f"""
You are an AI code patcher. A plugin named {plugin_name} failed its tests.
Here is the code:
