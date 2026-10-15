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
    assert captured["model"] == "deepseek/deepseek-v4-pro"
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


def test_erros_criticos_arte_usa_preflight_visual():
    import editorial
    # 7 palavras curtas: cabe visualmente — NÃO pode mais ser erro
    arte = {"titulo_principal": "Jazz no parque com shows ao vivo",
            "linha_apoio": "Sábado, 15h", "badge": "MÚSICA"}
    erros = editorial._erros_criticos_arte(arte, {"gratuito": True})
    assert not any("palavra" in e or "coube" in e for e in erros), erros


def test_erros_criticos_arte_rejeita_titulo_que_nao_cabe():
    import editorial
    arte = {"titulo_principal": "Inauguração extraordinariamente monumental " * 4,
            "linha_apoio": "x", "badge": "CULTURA"}
    erros = editorial._erros_criticos_arte(arte, {"gratuito": True})
    assert any("não cabe" in e for e in erros), erros


def test_validar_arte_titulo_curto_permanece():
    import editorial
    arte = {"titulo_principal": "Sarau Ameriafro", "linha_apoio": "Dia 16, na Estação Cultura",
            "badge": "CULTURA"}
    corrigida, alertas = editorial.validar_arte(arte, {"gratuito": True})
    assert corrigida["titulo_principal"] == "Sarau Ameriafro"


def _captura_prompts(monkeypatch):
    import llm_call as lc

    captured = {}

    def fake(system, user, model=None, max_tokens=None):
        captured["system"], captured["user"] = system, user
        return {"titulo_site": "T", "html": "<p>x</p>", "legenda_curta": "a", "legenda_contexto": "b"}

    monkeypatch.setattr(lc, "llm_call_json", fake)
    return captured


FATOS_COM_LACUNA = {"cidade": "Americana", "informacoes_ausentes": ["programação das atrações"],
                    "observacoes": ["faltam detalhes das atrações"]}


def test_gerar_conteudo_nao_mostra_o_que_falta_ao_redator(monkeypatch):
    import editorial

    captured = _captura_prompts(monkeypatch)
    editorial.gerar_conteudo("release", FATOS_COM_LACUNA, {})
    assert "informacoes_ausentes" not in captured["user"]
    assert "faltam detalhes" not in captured["user"]
    assert "Americana" in captured["user"]  # os fatos úteis continuam
    assert "NUNCA escreva sobre o que não se sabe" in captured["system"]


def test_gerar_legenda_nao_mostra_o_que_falta_ao_redator(monkeypatch):
    import editorial

    captured = _captura_prompts(monkeypatch)
    editorial.gerar_legenda(FATOS_COM_LACUNA, "resumo")
    assert "informacoes_ausentes" not in captured["user"]
    assert "NUNCA escreva sobre o que não se sabe" in captured["system"]


def test_gerar_conteudo_nao_exige_tamanho_minimo_fixo(monkeypatch):
    import editorial

    captured = _captura_prompts(monkeypatch)
    editorial.gerar_conteudo("release", {"cidade": "Americana"}, {})
    system = captured["system"]
    assert "Mínimo: 400 palavras" not in system  # forçava enchimento em releases curtos
    assert "release curto = matéria curta" in system
