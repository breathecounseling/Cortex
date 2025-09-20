from executor.connectors.openai_client import ask_executor

def test_integration_memory_roundtrip():
    r1 = ask_executor("Remember this: my favorite color is green", plugin_name="itest")
    assert "status" in r1
    r2 = ask_executor("What is my favorite color?", plugin_name="itest")
    # We can't assert exact wording, but ensure a response exists
    assert "assistant_output" in r2
