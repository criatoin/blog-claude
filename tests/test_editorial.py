"""Testa roteamento de modelo e sinalização de fallback em editorial."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "execution"))


def test_gerar_legenda_usa_modelo_criativo(monkeypatch):
    import editorial
    import llm_call as lc

    captured = {}

    def fake_llm_call_json(system, user, model=None):
        captured["model"] = model
        return {
            "legenda_curta": "a.\n\nb.\n\nc.\n\nd.",
            "legenda_contexto": "a.\n\nb.\n\nc.\n\nd.\n\ne.",
            "cta_sugerido": "x",
        }

    monkeypatch.setattr(lc, "llm_call_json", fake_llm_call_json)
    monkeypatch.delenv("CREATIVE_MODEL", raising=False)

    result = editorial.gerar_legenda({"gratuito": True}, "resumo")
    assert captured["model"] == "google/gemini-2.5-flash"
    assert "_fallback" not in result


def test_gerar_legenda_fallback_sinalizado(monkeypatch):
    import editorial
    import llm_call as lc

    def fake_llm_call_json(system, user, model=None):
        raise RuntimeError("api fora do ar")

    monkeypatch.setattr(lc, "llm_call_json", fake_llm_call_json)

    result = editorial.gerar_legenda({}, "resumo")
    assert result.get("_fallback"), "fallback deve vir sinalizado com motivo"


def test_gerar_conteudo_fallback_sinalizado(monkeypatch):
    import editorial
    import llm_call as lc

    def fake_llm_call_json(system, user, model=None):
        raise RuntimeError("api fora do ar")

    monkeypatch.setattr(lc, "llm_call_json", fake_llm_call_json)

    result = editorial.gerar_conteudo("release", {}, {})
    assert result.get("_fallback")
