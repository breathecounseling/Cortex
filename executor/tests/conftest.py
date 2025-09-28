import os
import sys
import shutil
import pytest

# ✅ Ensure the repo root (Cortex/) is on sys.path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

@pytest.fixture(autouse=True, scope="session")
def _cleanup_plugin_cache_dirs():
    base = os.path.join("executor", "plugins")
    if os.path.isdir(base):
        for entry in os.listdir(base):
            if entry.startswith("__") or entry.endswith("__"):
                p = os.path.join(base, entry)
                if os.path.isdir(p):
                    try:
                        shutil.rmtree(p)
                    except Exception:
                        pass
