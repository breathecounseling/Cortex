from executor.plugins.conversation_manager import conversation_manager as cm

def test_handle_repl_turn_formats_system_message():
    hist = [
        {"role": "user", "content": "Remember: my favorite color is green."},
        {"role": "assistant", "content": "Got it—I’ll remember that."},
    ]
    turn = cm.handle_repl_turn("What is my favorite color?", history=hist, session="test", limit=10)
    messages = turn["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "facts to remember" in messages[0]["content"].lower()
    assert messages[1]["role"] == "user"
