import os
import sys
import importlib
import pytest

from executor.plugins.builder import builder
from executor.plugins.builder import extend_plugin


def test_builder_creates_specialist(tmp_path):
    """Builder should create plugin.json and specialist.py for a new plugin."""
    plugin_name = "spec_builder_test"
    os.chdir(tmp_path)

    builder.main(plugin_name, "Builder test plugin")

    plugin_dir = tmp_path / "executor" / "plugins" / plugin_name
    assert (plugin_dir / "plugin.json").exists()
    assert (plugin_dir / "specialist.py").exists()


def test_extend_adds_specialist_if_missing(tmp_path):
    """Extend plugin should ensure specialist.py exists even if missing."""
    plugin_name = "spec_extend_test"
    os.chdir(tmp_path)

    # Extend should scaffold if plugin missing
    extend_plugin.extend_plugin(plugin_name, "extend test")
    plugin_dir = tmp_path / "executor" / "plugins" / plugin_name
    assert (plugin_dir / "specialist.py").exists()


def test_extend_updates_manifest_and_specialist(tmp_path):
    """Extend plugin should update manifest and leave specialist in place."""
    plugin_name = "spec_extend_manifest"
    os.chdir(tmp_path)

    builder.main(plugin_name, "Manifest test plugin")
    extend_plugin.extend_plugin(plugin_name, "update manifest")

    plugin_dir = tmp_path / "executor" / "plugins" / plugin_name
    manifest_path = plugin_dir / "plugin.json"
    assert manifest_path.exists()
    text = manifest_path.read_text()
    assert "specialist" in text
    assert (plugin_dir / "specialist.py").exists()


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

        # ✅ Clear import caches and stale entries
        importlib.invalidate_caches()
        sys.modules.pop(f"executor.plugins.{plugin_name}", None)
        sys.modules.pop(f"executor.plugins.{plugin_name}.specialist", None)

        # Import specialist freshly
        spec_mod = importlib.import_module(f"executor.plugins.{plugin_name}.specialist")

        # Verify contract functions
        assert hasattr(spec_mod, "can_handle")
        assert hasattr(spec_mod, "handle")
        assert hasattr(spec_mod, "describe_capabilities")

        result = spec_mod.handle({"goal": "demo"})
        assert isinstance(result, dict)
        assert "status" in result
        assert "message" in result
    finally:
        os.chdir(old_cwd)
