import os
import sys
import shutil
import pytest

# ✅ Ensure the repo root (Cortex/) is on sys.path
# This makes `import executor.connectors.repl` work no matter what cwd is.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

print(">>> Using sys.path[0] =", sys.path[0])  # DEBUG, can remove later


@pytest.fixture(autouse=True, scope="session")
def _cleanup_plugin_cache_dirs():
    """
    Clean up any leftover temp plugin dirs like executor/plugins/__xyz__.
    """
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