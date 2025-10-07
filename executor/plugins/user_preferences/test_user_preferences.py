from executor.plugins.user_preferences import user_preferences as up

def test_run_returns_ok():
    """run() should return ok status and data dict even when no key/value provided."""
    result = up.run()
    assert result["status"] == "ok"
    assert isinstance(result["data"], dict)

def test_set_and_get_roundtrip(tmp_path):
    """Setting a preference stores it, and getting it retrieves the same value."""
    # direct handle call for realistic flow
    up.handle({"action": "set", "key": "theme", "value": "dark"})
    res = up.handle({"action": "get", "key": "theme"})
    assert res["status"] == "ok"
    assert res["data"]["value"] == "dark"