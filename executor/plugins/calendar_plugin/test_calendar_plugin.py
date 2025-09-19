import calendar_plugin

def test_run():
    result = calendar_plugin.run()
    assert result["status"] == "ok"
