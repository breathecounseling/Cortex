from executor.plugins.task_planner import task_planner

def test_plan():
    result = task_planner.plan("Build a chatbot")
    assert "subtasks" in result
    assert isinstance(result["subtasks"], list)
    assert len(result["subtasks"]) >= 1
