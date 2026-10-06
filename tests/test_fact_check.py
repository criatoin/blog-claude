"""Testa a checagem factual: camada de código (entidades) e camada Jev (mockada)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "execution"))

import fact_check as fc

RELEASE_MAC = """*MAC Americana exibe comédia clássica sul-coreana em sessão gratuita nesta segunda*

O filme sul-coreano “O Dia do Casamento” será exibido nesta segunda-feira
(4), às 19h30, na Sessão Pontos MIS, realizada no Museu de Arte
Contemporânea (MAC) de Americana, localizado no Centro de Cultura e Lazer
(CCL), na Avenida Brasil, nº 1.293, Jardim São Paulo. A entrada é gratuita,
e a classificação indicativa é de 10 anos.

Informações: (19) 3461-1234 ou cultura@americana.sp.gov.br.
Ingressos em www.sympla.com.br/evento/mac-coreia. Siga @macamericana.

Texto: João Coutinho (MTb 35.570)
04/05/2026"""


def _codigo(texto_materia: str, release: str = RELEASE_MAC) -> list[dict]:
    return fc.checar_entidades(fc.texto_limpo(release), {"html": texto_materia})


# ─── Camada 1: entidades ──────────

def test_dados_iguais_ao_release_passam():
    materia = ("Na segunda-feira (4 de maio), às 19h30, o MAC exibe o filme na Avenida Brasil, nº 1.293. "
               "Entrada gratuita. Informações: (19) 3461-1234, cultura@americana.sp.gov.br, "
               "sympla.com.br/evento/mac-coreia e @macamericana.")
    assert _codigo(materia) == []


def test_formatos_diferentes_do_mesmo_dado_passam():
    # 19:30 == 19h30; "dia 4" casa com "(4)"; 04/05 casa com "4 de maio"
    assert _codigo("A sessão do dia 4 começa às 19:30, em 04/05.") == []


def test_horario_errado_bloqueia():
    problemas = _codigo("A sessão começa às 20h.")
    assert [p["trecho"] for p in problemas] == ["20h00"]
    assert problemas[0]["origem"] == "codigo"


def test_data_errada_bloqueia():
    problemas = _codigo("A sessão é no dia 5 de maio.")
    assert {p["trecho"] for p in problemas} == {"05/05"}


def test_valor_inventado_bloqueia():
    problemas = _codigo("O ingresso custa R$ 10,00.")
    assert problemas and problemas[0]["motivo"] == "valor não consta no release"


def test_gratuidade_inventada_bloqueia():
    release_pago = "Show na praça central, dia 10 de maio, às 20h. Ingressos a R$ 30."
    problemas = _codigo("O show é gratuito.", release=release_pago)
    assert [p["trecho"] for p in problemas] == ["gratuito"]


def test_telefone_link_email_perfil_inventados_bloqueiam():
    problemas = _codigo("Ligue (19) 3461-9999, veja www.mac.com.br, mande e-mail para x@mac.com.br ou siga @mac_oficial.")
    motivos = {p["motivo"] for p in problemas}
    assert motivos == {"telefone não consta no release", "link não consta no release",
                       "e-mail não consta no release", "perfil não consta no release"}


def test_intervalo_de_anos_nao_vira_telefone():
    release = "A temporada 2025-2026 da orquestra começa dia 10 de maio."
    assert _codigo("Temporada 2025/2026 começa dia 10 de maio.", release=release) == []


def test_ddd_entre_parenteses_nao_vira_data():
    ent = fc.extrair_entidades("Telefone (19) 3461-1234")
    assert ent["datas"] == set()


def test_lista_de_dias_herda_o_mes():
    release = "O congresso acontece entre os dias 26 e 29 de abril, no Rio."
    assert _codigo("O congresso vai de 26 a 29 de abril.", release=release) == []


def test_medida_com_h_nao_vira_horario():
    assert fc.extrair_entidades("área de 10 hectares")["horarios"] == set()


# ─── Divisão de texto ──────────

def test_dividir_frases_respeita_abreviacoes():
    frases = fc.dividir_frases("O MAC fica na Av. Brasil, 1.293. A entrada é gratuita.")
    assert frases == ["O MAC fica na Av. Brasil, 1.293.", "A entrada é gratuita."]


def test_frases_para_checar_separa_blocos_e_ignora_dado_ausente():
    post = {"html": "<p>Filme coreano no MAC. Sessão às 19h30 na segunda.</p>"
                    "<h2>Serviço</h2><ul><li><strong>Quando:</strong> segunda-feira (4), às 19h30</li>"
                    "<li>Onde: [DADO AUSENTE: endereço] no centro</li></ul>",
            "titulo_site": "MAC exibe clássico coreano"}
    campos = fc.campos_do_post(post)
    frases = [f for _, f in fc.frases_para_checar(post, campos)]
    assert "Quando: segunda-feira (4), às 19h30" in frases
    assert not any("DADO AUSENTE" in f for f in frases)
    assert "Serviço" not in frases  # heading de 1 palavra não vai ao Jev
    assert "MAC exibe clássico coreano" in frases


# ─── Camada 2: Jev (mockado) e status ──────────

def _fake_jev(veredito_por_trecho: dict[str, str], default: str = "supported"):
    def fake(release, frase):
        choice = next((v for t, v in veredito_por_trecho.items() if t in frase), default)
        if choice == "ERRO":
            raise RuntimeError("timeout")
        return {"choice": choice, "probabilities": {choice: 1.0}, "cost": 0.00004}
    return fake


POST_OK = {
    "titulo_site": "MAC Americana exibe clássico coreano",
    "html": "<p>O filme O Dia do Casamento passa na segunda-feira (4), às 19h30, no MAC.</p>"
            "<p>Programa perfeito para começar a semana.</p>",
}


def test_tudo_suportado_aprova(monkeypatch):
    monkeypatch.setattr(fc, "jev_classificar", _fake_jev({"Programa perfeito": "opinion"}))
    r = fc.verificar_post(RELEASE_MAC, POST_OK)
    assert r["status"] == "aprovado"
    assert r["bloqueantes"] == [] and r["alertas"] == []
    assert r["frases_checadas"] == 3
    assert r["custo_usd"] > 0


def test_informacao_inventada_bloqueia(monkeypatch):
    post = {**POST_OK, "html": POST_OK["html"] + "<p>Após o filme, haverá debate com o diretor.</p>"}
    monkeypatch.setattr(fc, "jev_classificar", _fake_jev({"debate": "insufficient_evidence"}))
    r = fc.verificar_post(RELEASE_MAC, post)
    assert r["status"] == "bloqueado"
    assert r["bloqueantes"][0]["motivo"] == "informação que não está no release"
    assert r["bloqueantes"][0]["campo"] == "html"


def test_jev_fora_do_ar_nunca_aprova(monkeypatch):
    monkeypatch.setattr(fc, "jev_classificar", _fake_jev({}, default="ERRO"))
    r = fc.verificar_post(RELEASE_MAC, POST_OK)
    assert r["status"] == "incompleto"
    assert r["nao_checadas"] == 3


def test_sem_chave_openrouter_nunca_aprova(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    r = fc.verificar_post(RELEASE_MAC, POST_OK)
    assert r["status"] == "incompleto"


def test_post_vazio_nao_aprova(monkeypatch):
    monkeypatch.setattr(fc, "jev_classificar", _fake_jev({}))
    r = fc.verificar_post(RELEASE_MAC, {"html": ""})
    assert r["status"] == "incompleto"


def test_risco_intermediario_vira_alerta(monkeypatch):
    def fake(release, frase):
        return {"choice": "opinion", "probabilities": {"opinion": 0.55, "insufficient_evidence": 0.45}, "cost": 0}
    monkeypatch.setattr(fc, "jev_classificar", fake)
    r = fc.verificar_post(RELEASE_MAC, {"html": "<p>Quem gosta de k-drama vai reconhecer muita coisa.</p>"})
    assert r["status"] == "aprovado"
    assert len(r["alertas"]) == 1


def test_erro_de_codigo_bloqueia_mesmo_com_jev_aprovando(monkeypatch):
    monkeypatch.setattr(fc, "jev_classificar", _fake_jev({}))
    r = fc.verificar_post(RELEASE_MAC, {"html": "<p>A sessão começa às 21h no MAC de Americana.</p>"})
    assert r["status"] == "bloqueado"
    assert r["bloqueantes"][0]["origem"] == "codigo"


def test_jev_classificar_repete_uma_vez_em_erro_5xx(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(fc.time, "sleep", lambda s: None)
    chamadas = []

    class Resp:
        def __init__(self, status, body=None):
            self.status_code, self._body, self.text = status, body, "erro"
        def json(self):
            return self._body

    def fake_post(url, headers, json, timeout):
        chamadas.append(1)
        if len(chamadas) == 1:
            return Resp(503)
        return Resp(200, {"answers": {"verdict": {"choice": "supported", "probabilities": {"supported": 1},
                                                  "confidence": 1}}, "usage": {"cost": 0.00004}})

    monkeypatch.setattr(fc.requests, "post", fake_post)
    r = fc.jev_classificar("release", "frase")
    assert r["choice"] == "supported" and len(chamadas) == 2


def test_linha_card():
    assert fc.linha_card({"status": "aprovado", "frases_checadas": 24, "alertas": []}) == \
        "✅ Checagem: 24 frases conferidas com o release"
    assert fc.linha_card({"status": "bloqueado", "bloqueantes": [{}, {}]}).startswith("⛔ Checagem: 2 problema(s)")
    assert fc.linha_card({"status": "incompleto", "nao_checadas": 3}).startswith("⚠️ Checagem incompleta: 3")
    assert fc.linha_card({}) == "⚠️ Checagem não rodou"
