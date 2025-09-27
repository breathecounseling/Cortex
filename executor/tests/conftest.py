import subprocess
import sys
import os

def pytest_sessionstart(session):
    """Run before the test suite starts — ensures specialists exist."""
    script = os.path.join("scripts", "add_specialists.py")
    print("[conftest] Ensuring all plugins have specialists before tests...")
    subprocess.run([sys.executable, script], check=False)