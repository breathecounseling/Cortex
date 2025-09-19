from executor.plugins.task_planner import task_planner

def test_run():
    result = task_planner.run()
    assert result["status"] == "ok"
