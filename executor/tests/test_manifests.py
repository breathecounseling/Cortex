import os
import json
import importlib
import pytest

from executor.plugins.builder.builder import main as build_plugin
from executor.plugins.builder.extend_plugin import extend_plugin

BASE = os.path.join("executor", "plugins")


def test_all_plugins_have_manifest_and_specialist():
    """
    Every plugin folder should include plugin.json and specialist.py,
    and manifest must include a 'specialist' path.
    """
    for entry in os.listdir(BASE):
        plugin_dir = os.path.join(BASE, entry)
        if not os.path.isdir(plugin_dir):
            continue

        # manifest must exist
        manifest_path = os.path.join(plugin_dir, "plugin.json")
        assert os.path.exists(manifest_path), f"{entry} missing plugin.json"

        # load manifest
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "name" in data, f"{entry} manifest missing 'name'"
        assert "description" in data, f"{entry} manifest missing 'description'"
        assert "capabilities" in data, f"{entry} manifest missing 'capabilities'"
        assert isinstance(data["capabilities"], list), f"{entry} capabilities must be a list"
        assert "specialist" in data, f"{entry} manifest missing 'specialist'"

        # specialist file must exist
        specialist_file = os.path.join(plugin_dir, "specialist.py")
        assert os.path.exists(specialist_file), f"{entry} missing specialist.py"

        # specialist module must import and expose contract functions
        try:
            spec_mod = importlib.import_module(data["specialist"])
            for fn in ["can_handle", "handle", "describe_capabilities"]:
                assert hasattr(spec_mod, fn), f"{entry} specialist missing {fn}"
        except Exception as e:
            pytest.fail(f"{entry} specialist import failed: {e}")


def test_builder_creates_manifest_and_specialist(tmp_path):
    """
    Builder should scaffold plugin.json and specialist.py.
    """
    plugin_name = "dummy_plugin"
    target = tmp_path / "executor" / "plugins" / plugin_name
    os.makedirs(target.parent, exist_ok=True)

    # temporarily swap BASE
    old_base = os.getcwd()
    os.chdir(tmp_path)

    try:
        build_plugin(plugin_name, "Dummy plugin for testing")
        manifest_path = target / "plugin.json"
        assert manifest_path.exists()
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["name"] == plugin_name
        assert isinstance(data["capabilities"], list)
        assert "specialist" in data

        specialist_file = target / "specialist.py"
        assert specialist_file.exists(), "builder did not create specialist.py"
    finally:
        os.chdir(old_base)


def test_extend_updates_manifest_and_specialist(tmp_path):
    """
    extend_plugin should update plugin.json with new capability and ensure specialist exists.
    """
    plugin_name = "extender_test"
    base = tmp_path / "executor" / "plugins" / plugin_name
    os.makedirs(base, exist_ok=True)
    os.makedirs(base / "tests", exist_ok=True)

    # scaffold plugin.json manually
    manifest = {"name": plugin_name, "description": "test", "capabilities": []}
    with open(base / "plugin.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f)

    # create minimal plugin + test file so pytest passes
    plugin_file = base / f"{plugin_name}.py"
    plugin_file.write_text("def foo():\n    return 1\n")
    test_file = base / "test_extender.py"
    test_file.write_text("from executor.plugins.extender_test import extender_test\n\ndef test_dummy():\n    assert True\n")

    # temporarily swap BASE
    old_base = os.getcwd()
    os.chdir(tmp_path)

    try:
        res = extend_plugin(plugin_name, "add foo function")
        assert res["status"] in {"ok", "tests_failed", "model_error"}  # model may not run in test
        # check manifest updated
        with open(base / "plugin.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "add foo function" in data["capabilities"], "extend_plugin did not update manifest"
        assert "specialist" in data, "extend_plugin did not ensure specialist path"
        assert os.path.exists(base / "specialist.py"), "extend_plugin did not create specialist.py"
    finally:
        os.chdir(old_base)
