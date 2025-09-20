from executor.plugins.user_preferences import user_preferences

def test_run():
    result = user_preferences.run()
    assert result["status"] == "ok"
