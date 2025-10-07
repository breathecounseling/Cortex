from executor.plugins.budget_monitor import budget_monitor

def test_record_and_check():
    state = budget_monitor.record_usage(10)
    assert "used" in state
    res = budget_monitor.check_budget()
    assert "ok" in res and "used" in res and "limit" in res
