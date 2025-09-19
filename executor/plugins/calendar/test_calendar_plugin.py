import calendar

def test_run():
    result = calendar.run()
    assert result["status"] == "ok"
