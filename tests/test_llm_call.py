"""Testa json_mode e creative_model de llm_call."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "execution"))


def test_json_mode_envia_response_format(monkeypatch):
    import llm_call as lc

    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": '{"ok": true}'}}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return FakeResp()

    monkeypatch.setattr(lc.requests, "post", fake_post)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    result = lc.llm_call_json(system="s", user="u")
    assert result == {"ok": True}
    assert captured["payload"]["response_format"] == {"type": "json_object"}


def test_sem_json_mode_nao_envia_response_format(monkeypatch):
    import llm_call as lc

    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "texto"}}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return FakeResp()

    monkeypatch.setattr(lc.requests, "post", fake_post)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    lc.llm_call(system="s", user="u")
    assert "response_format" not in captured["payload"]


def test_creative_model_padrao(monkeypatch):
    import llm_call as lc
    monkeypatch.delenv("CREATIVE_MODEL", raising=False)
    assert lc.creative_model() == "google/gemini-2.5-flash"


def test_creative_model_env(monkeypatch):
    import llm_call as lc
    monkeypatch.setenv("CREATIVE_MODEL", "anthropic/claude-haiku-4.5")
    assert lc.creative_model() == "anthropic/claude-haiku-4.5"
