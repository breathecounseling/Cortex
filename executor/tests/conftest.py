import os
import sys
import shutil
import pytest

# --- Ensure imports always work, even after chdir into tmp dirs ---

# Absolute path to repo root (Cortex/)
HERE = os.path.abspath(os.path.dirname(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Also add executor/ directly as an extra safety net
EXECUTOR_DIR = os.path.join(ROOT, "executor")
if EXECUTOR_DIR not in sys.path:
    sys.path.insert(0, EXECUTOR_DIR)

# --- Fixtures ---

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