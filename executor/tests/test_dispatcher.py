import os
import json
import importlib
import pytest

from executor.plugins.builder import builder
from executor.core.registry import SpecialistRegistry
from executor.core.dispatcher import Dispatcher


def test_dispatcher_with_scaffolded_specialist(tmp_path):
    """Dispatcher should route an action to a specialist and get a valid dict result."""

    plugin_name = "dispatch_test_plugin"
    base = tmp_path / "executor" / "plugins" / plugin_name
    os.makedirs(base.parent, exist_ok=True)

    # Run builder to scaffold plugin + specialist
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        builder.main(plugin_name, "Dispatcher test plugin")

        # Registry should now find the plugin and specialist
        registry = SpecialistRegistry(base=str(tmp_path / "executor" / "plugins"))
        assert registry.has_plugin(plugin_name), "Registry did not find plugin"
        specialist = registry.get_specialist(plugin_name)
        assert specialist, "Registry did not load specialist"

        # Create Dispatcher
        dispatcher = Dispatcher(registry)

        # Build a fake action
        action = {
            "plugin": plugin_name,
            "goal": "test goal",
            "status": "ready",
            "args": {}
        }

        # Dispatch the action
        result = dispatcher.dispatch(action)
        assert isinstance(result, dict), "Dispatcher result must be dict"
        assert "status" in result and "message" in result, "Missing required keys in result"
        assert result["status"] in {"ok", "error", "skipped"}
    finally:
        os.chdir(old_cwd)
