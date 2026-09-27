"""The OpenAI client sends JSON-mode chat completions with the configured model per role."""

import types

import pytest

from agrimon.config import load_settings
from agrimon.config.llm import LLMError, OpenAIJsonClient, make_llm_client

from tests.conftest import make_project


class _FakeCompletions:
    def __init__(self, content):
        self.content, self.kwargs = content, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        msg = types.SimpleNamespace(content=self.content)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])


def _client(tmp_path, monkeypatch, content):
    root = make_project(tmp_path, seed=False)
    (root / ".env").write_text("OPENAI_API_KEY=sk-test\n")
    settings = load_settings(root)
    fake = _FakeCompletions(content)
    import openai

    monkeypatch.setattr(openai, "OpenAI", lambda **kw: types.SimpleNamespace(chat=types.SimpleNamespace(completions=fake)))
    return OpenAIJsonClient(settings), fake


def test_request_shape(tmp_path, monkeypatch):
    client, fake = _client(tmp_path, monkeypatch, '{"ok": true}')
    assert client.complete_json("generation", "sys", "user") == {"ok": True}
    assert fake.kwargs["model"] == "gpt-4o-mini"
    assert fake.kwargs["response_format"] == {"type": "json_object"}
    assert fake.kwargs["messages"][0] == {"role": "system", "content": "sys"}


def test_invalid_json_raises(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch, "not json")
    with pytest.raises(LLMError):
        client.complete_json("intent", "s", "u")


def test_no_key_means_no_client(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    root = make_project(tmp_path, seed=False)
    assert make_llm_client(load_settings(root)) is None
