import pytest

# Stub OpenAIClient for all tests unless explicitly overridden
@pytest.fixture(autouse=True)
def stub_openai(monkeypatch):
    class DummyClient:
        def chat(self, messages, response_format=None):
            return '{"assistant_message":"stubbed","actions":[],"tasks_to_add":[]}'
    from executor.connectors import openai_client
    monkeypatch.setattr(openai_client, "OpenAIClient", lambda: DummyClient())
