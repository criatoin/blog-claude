"""Testa o laço checa → corrige → checa (editorial_checagem) e o card do Telegram."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "execution"))

POST = {
    "titulo_site": "MAC exibe clássico coreano",
    "subtitulo": "",
    "resumo_telegram": "Sessão na segunda.",
    "html": "<p>Sessão às 20h no MAC, com debate após o filme.</p>",
    "texto_arte": {"titulo_principal": "Clássico coreano no MAC", "linha_apoio": ""},
}
BLOQUEADO = {"status": "bloqueado", "bloqueantes": [
    {"campo": "html", "trecho": "20h00", "motivo": "horário não consta no release", "origem": "codigo"}],
    "alertas": [], "frases_checadas": 3, "nao_checadas": 0, "custo_usd": 0.0001}
APROVADO = {"status": "aprovado", "bloqueantes": [], "alertas": [],
            "frases_checadas": 3, "nao_checadas": 0, "custo_usd": 0.0001}


def test_checar_e_corrigir_reescreve_e_aprova(monkeypatch):
    import editorial_checagem as editorial
    import fact_check as fc
    import llm_call as lc

    resultados = iter([BLOQUEADO, APROVADO])
    monkeypatch.setattr(fc, "verificar_post", lambda release, post, legenda="": next(resultados))
    pedidos = []

    def fake_llm(system, user, model=None, max_tokens=None):
        pedidos.append(user)
        return {**{k: POST[k] for k in fc.CAMPOS_CORRIGIVEIS},
                "html": "<p>Sessão às 19h30 no MAC, com debate após o filme.</p>"}

    monkeypatch.setattr(lc, "llm_call_json", fake_llm)
    post, checagem = editorial.checar_e_corrigir("release", POST, "legenda")
    assert checagem["status"] == "aprovado"
    assert "19h30" in post["html"]
    assert post["texto_arte"] == POST["texto_arte"]  # arte não é tocada
    assert "20h00" in pedidos[0]  # o problema exato vai para o redator


def test_checar_e_corrigir_para_apos_duas_tentativas(monkeypatch):
    import editorial_checagem as editorial
    import fact_check as fc
    import llm_call as lc

    chamadas = []
    monkeypatch.setattr(fc, "verificar_post", lambda release, post, legenda="": chamadas.append(1) or BLOQUEADO)
    monkeypatch.setattr(lc, "llm_call_json", lambda system, user, model=None, max_tokens=None: dict(POST))
    post, checagem = editorial.checar_e_corrigir("release", POST)
    assert checagem["status"] == "bloqueado"
    assert len(chamadas) == 3  # checagem inicial + 2 rechecagens


def test_problema_so_na_arte_nao_dispara_reescrita(monkeypatch):
    import editorial_checagem as editorial
    import fact_check as fc
    import llm_call as lc

    so_arte = {**BLOQUEADO, "bloqueantes": [
        {"campo": "arte", "trecho": "gratuito", "motivo": "release não diz que é gratuito", "origem": "codigo"}]}
    monkeypatch.setattr(fc, "verificar_post", lambda release, post, legenda="": so_arte)

    def nao_chamar(*a, **k):
        raise AssertionError("não deveria reescrever")

    monkeypatch.setattr(lc, "llm_call_json", nao_chamar)
    _, checagem = editorial.checar_e_corrigir("release", POST)
    assert checagem["status"] == "bloqueado"


def test_corrigir_texto_rejeita_html_encolhido(monkeypatch):
    import editorial_checagem as editorial
    import llm_call as lc

    monkeypatch.setattr(lc, "llm_call_json",
                        lambda system, user, model=None, max_tokens=None: {**POST, "html": "<p>x</p>"})
    assert editorial.corrigir_texto("release", POST, BLOQUEADO["bloqueantes"]) == {}


def test_corrigir_texto_falha_de_api_devolve_vazio(monkeypatch):
    import editorial_checagem as editorial
    import llm_call as lc

    def falha(*a, **k):
        raise RuntimeError("api fora do ar")

    monkeypatch.setattr(lc, "llm_call_json", falha)
    assert editorial.corrigir_texto("release", POST, BLOQUEADO["bloqueantes"]) == {}


def test_resumo_telegram_leva_linha_e_problemas_da_checagem():
    import editorial_checagem as editorial

    meta = editorial.resumo_telegram(POST, BLOQUEADO, {"cidade": "Americana"})
    assert meta["checagem"].startswith("⛔ Checagem: 1 problema(s)")
    assert meta["alertas"] == ["20h00: horário não consta no release"]


def test_card_do_telegram_mostra_linha_de_checagem(monkeypatch):
    import telegram_notify as tn

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    monkeypatch.setattr(tn, "_load_pending", lambda: {})
    monkeypatch.setattr(tn, "_save_pending", lambda data: None)
    captured = {}

    def fake_api(method, poll_timeout=0, **kwargs):
        captured["text"] = kwargs["json"]["text"]
        return {"ok": True, "result": {"message_id": 1}}

    monkeypatch.setattr(tn, "_api", fake_api)
    tn.cmd_send_release(1, "Título", "resumo", "https://x/edit", "nao-existe.jpg", "0",
                        card_meta={"checagem": "✅ Checagem: 12 frases conferidas com o release"})
    assert "✅ Checagem: 12 frases conferidas com o release" in captured["text"]
