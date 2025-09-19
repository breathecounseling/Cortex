from executor.plugins.conversation_manager import conversation_manager

def test_run():
    result = conversation_manager.run()
    assert result["status"] == "ok"
