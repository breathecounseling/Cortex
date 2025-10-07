import subprocess
import sys

def test_add_manifests_dry_run():
    """Ensure the add_manifests script runs in dry mode without error."""
    result = subprocess.run(
        [sys.executable, "scripts/add_manifests.py", "--dry"],
        capture_output=True,
        text=True
    )
    # It should complete successfully
    assert result.returncode == 0
    # It should print either "All plugins have manifests" or "Missing manifest"
    assert "manifest" in result.stdout.lower()
