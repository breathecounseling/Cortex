# executor/tests/test_integration.py
from executor.connectors.openai_client import OpenAIClient

def test_chat_roundtrip(monkeypatch):
    client = OpenAIClient(model="gpt-4o-mini")

    # Stub the API call
    def fake_chat(messages, response_format=None):
        return "Hello world"
    monkeypatch.setattr(client, "chat", fake_chat)

    res = client.chat([{"role": "user", "content": "hi"}])
    assert res == "Hello world"
