from executor.plugins.userpreferences import userpreferences

def test_run():
    result = userpreferences.run()
    assert result["status"] == "ok"
