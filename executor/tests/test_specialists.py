import os
import importlib
import json
import pytest

from executor.plugins.builder import builder
from executor.plugins.builder.extend_plugin import extend_plugin


def test_builder_creates_specialist(tmp_path):
    """Builder should scaffold specialist.py and manifest entry."""
    plugin_name = "spec_test_plugin"
    target = tmp_path / "executor" / "plugins" / plugin_name
    os.makedirs(target.parent, exist_ok=True)

    # Run builder in temp dir
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        builder.main(plugin_name, "Plugin for testing specialists")
        # specialist.py must exist
        specialist_file = target / "specialist.py"
        assert specialist_file.exists(), "builder did not create specialist.py"

        # manifest must include specialist path
        manifest_path = target / "plugin.json"
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        assert "specialist" in manifest
        assert manifest["specialist"] == f"executor.plugins.{plugin_name}.specialist"
    finally:
        os.chdir(old_cwd)


def test_extend_adds_specialist_if_missing(tmp_path, monkeypatch):
    """extend_plugin should ensure specialist.py + manifest entry exist."""
    plugin_name = "spec_extender_test"
    base = tmp_path / "executor" / "plugins" / plugin_name
    os.makedirs(base, exist_ok=True)
    os.makedirs(base / "tests", exist_ok=True)

    # minimal manifest without specialist
    manifest = {"name": plugin_name, "description": "test", "capabilities": []}
    with open(base / "plugin.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f)

    # minimal plugin + test
    plugin_file = base / f"{plugin_name}.py"
    plugin_file.write_text("def foo():\n    return 1\n")
    test_file = base / "test_dummy.py"
    test_file.write_text("def test_dummy():\n    assert True\n")

    # swap cwd
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        res = extend_plugin(plugin_name, "add foo function")
        assert res["status"] in {"ok", "failed", "tests_failed", "model_error"}

        # specialist must exist after extension
        specialist_file = base / "specialist.py"
        assert specialist_file.exists(), "extend_plugin did not create specialist.py"

        # manifest must include specialist
        with open(base / "plugin.json", "r", encoding="utf-8") as f:
            updated = json.load(f)
        assert "specialist" in updated
        assert updated["specialist"] == f"executor.plugins.{plugin_name}.specialist"
    finally:
        os.chdir(old_cwd)


def test_specialist_contract(tmp_path):
    """Specialist must implement can_handle, handle, describe_capabilities."""
    plugin_name = "spec_contract_test"
    base = tmp_path / "executor" / "plugins" / plugin_name
    os.makedirs(base, exist_ok=True)

    # Scaffold with builder
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        builder.main(plugin_name, "Contract test plugin")

        # import specialist
        spec_mod = importlib.import_module(f"executor.plugins.{plugin_name}.specialist")

        # must expose contract functions
        assert hasattr(spec_mod, "can_handle")
        assert hasattr(spec_mod, "handle")
        assert hasattr(spec_mod, "describe_capabilities")

        # test handle basic call
        intent = {"plugin": plugin_name, "goal": "test goal", "status": "ready", "args": {}}
        res = spec_mod.handle(intent)
        assert isinstance(res, dict)
        assert "status" in res and "message" in res
    finally:
        os.chdir(old_cwd)
