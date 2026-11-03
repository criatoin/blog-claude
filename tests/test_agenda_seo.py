"""Testa a agenda publicada na íntegra, os campos de SEO e a checagem de cobertura."""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "execution"))
for _m in ("requests", "dotenv"):                      # fact_check importa; os testes não fazem rede
    if _m not in sys.modules:
        try:
            __import__(_m)
        except ImportError:
            _mod = types.ModuleType(_m)
            _mod.load_dotenv = lambda *a, **k: None
            sys.modules[_m] = _mod

import agenda_release as ar
import fact_check as fc
import seo_fields as sf

RELEASE = (
    "Agenda cultural de novembro tem festivais de jazz e de cultura\r\r\n"
    "afro-brasileira em Americana\r\r\n\r\r\n"
    "A agenda de novembro em Americana tem o Juca Jazz Festival 2026, com entrada\r\r\ngratuita.\r\r\n\r\r\n"
    "Confira a programação completa:\r\r\n\r\r\n"
    "04/11 (quarta-feira)\r\r\n\r\r\n"
    "O Clube de Leitura se reúne das 19h às 21h na Biblioteca (Praça Müller, 172).\r\r\nEntrada gratuita.\r\r\n\r\r\n"
    "04, 05 e 06 (quarta, quinta e sexta-feira)\r\r\n\r\r\n"
    "Observação de Saturno às 21h no OMA. Agendamento pelo (19) 3408-4800.\r\r\n\r\r\n"
    "07 e 08/11 (sábado e domingo)\r\r\n\r\r\n"
    "O Taurus Festival ocorre das 12h às 22h no CCL.\r\r\n\r\r\n"
    "07 e 08/11 (sábado e domingo)\r\r\n\r\r\n"
    "A dança “40 Anos” custa R$ 50,00 a R$ 100,00 em www.ingressodigital.com.\r\r\n\r\r\n"
    "De 10 a 13/11 (terça a sexta-feira)\r\r\n\r\r\n"
    "O CCL recebe a Fábrica de Cultura das 13h às 21h. Agendamentos: mac@americana.sp.gov.br.\r\r\n\r\r\n"
    "Todas as terças-feiras, das 18h às 21h\r\r\n\r\r\n"
    "Ensaios do Maracatu Estação Quilombo.\r\r\n\r\r\n"
    "Texto: Beatriz Costa (MTb 39.517)\r\r\n\r\r\n"
    "Créditos nas fotos\r\r\n\r\r\n"
    "03/11/2026\r\r\n"
)


def test_detecta_agenda_e_ignora_release_comum():
    assert ar.eh_agenda(RELEASE)
    assert not ar.eh_agenda("Show gratuito no sábado, 16/05, às 19h, na Estação Cultura.\n\nMais detalhes em breve.")


def test_normaliza_quebras_de_linha_do_email():
    p = ar.parse_agenda(RELEASE)
    assert len(p["blocos"]) == 6
    assert p["titulo_release"].startswith("Agenda cultural de novembro")
    assert not any("\n" in x or "\r" in x for x in p["intro"])


def test_nao_confunde_data_de_envio_com_bloco():
    p = ar.parse_agenda(RELEASE)
    assert "03/11/2026" not in [b["cabecalho"] for b in p["blocos"]]
    assert p["rodape"][0].startswith("Texto: Beatriz Costa")


def test_todo_bloco_do_release_vai_para_o_html_sem_reescrever():
    post = ar.montar_post_agenda(RELEASE)
    h = post["html"]
    for trecho in ("Clube de Leitura se reúne das 19h às 21h", "Observação de Saturno às 21h",
                   "Taurus Festival ocorre das 12h às 22h", "R$ 50,00 a R$ 100,00", "Fábrica de Cultura",
                   "Maracatu Estação Quilombo"):
        assert trecho in h
    assert h.count("<h3>07 e 08/11 (sábado e domingo)</h3>") == 1      # cabeçalho repetido em sequência é mesclado
    assert post["_blocos"] == 6


def test_html_tem_links_e_aviso_de_integra():
    h = ar.montar_post_agenda(RELEASE, {"instituicao_realizadora": "Secretaria de Cultura"})["html"]
    assert '<a href="https://www.ingressodigital.com"' in h
    assert '<a href="mailto:mac@americana.sp.gov.br">' in h
    assert "publicadas na íntegra pelo +blog" in h
    assert "Texto: Beatriz Costa (MTb 39.517)" in h
    assert "03/11/2026" not in h


def test_titulo_slug_e_categoria_deterministicos():
    post = ar.montar_post_agenda(RELEASE)
    assert post["titulo_site"] == "Agenda cultural de novembro em Americana"
    assert post["slug"] == "agenda-cultural-novembro-americana"
    assert post["wp_category_id"] == 19
    assert len(post["titulo_site"]) <= 65


def test_cabecalhos_ficam_exatamente_como_no_release():
    h = ar.montar_post_agenda(RELEASE)["html"]
    assert "<h3>04, 05 e 06 (quarta, quinta e sexta-feira)</h3>" in h      # sem inventar o mês
    assert "<h3>De 10 a 13/11 (terça a sexta-feira)</h3>" in h
    assert "<h3>Todas as terças-feiras, das 18h às 21h</h3>" in h


def test_agenda_nao_inventa_dados_e_cobre_o_release():
    post = ar.montar_post_agenda(RELEASE)
    rel = fc.texto_limpo(RELEASE)
    txt = " ".join(fc.html_para_blocos(post["html"]))
    assert fc.checar_entidades(rel, {"html": txt}) == []
    faltando = fc.checar_cobertura(rel, txt)
    assert all("03/11" in f["motivo"] for f in faltando)      # só a data de envio do release fica de fora


# ─── cobertura (checagem inversa) ──────────

def test_cobertura_acusa_dado_do_release_que_sumiu_da_materia():
    rel = "Show dia 10/05 às 19h30. Ingressos R$ 40,00 pelo (19) 3408-4800."
    alertas = fc.checar_cobertura(rel, "Show gratuito em maio.")
    motivos = " ".join(a["motivo"] for a in alertas)
    assert "10/05" in motivos and "19h30" in motivos and "R$ 40,00" in motivos and "34084800" in motivos


def test_cobertura_nao_acusa_quando_tudo_esta_na_materia():
    rel = "Show dia 10/05 às 19h30. Ingressos R$ 40,00."
    assert fc.checar_cobertura(rel, "O show é em 10 de maio, às 19h30, e custa R$ 40,00.") == []


# ─── SEO ──────────

def test_descricao_corta_em_frase_e_cabe_no_limite():
    html = ("<p>A feira de artesanato volta ao centro de Americana neste sábado, com 40 expositores e música ao vivo. "
            "Entrada gratuita.</p><p>Outro parágrafo que não deve entrar porque já passou do limite de caracteres da "
            "meta description do Google.</p>")
    d = sf.descricao_da_materia(html)
    assert d.startswith("A feira de artesanato volta") and len(d) <= sf.LIMITE_DESCRICAO
    assert d.endswith(".")


def test_descricao_longa_corta_em_palavra_inteira_com_reticencias():
    html = "<p>" + "Palavra " * 60 + "fim.</p>"
    d = sf.descricao_da_materia(html)
    assert len(d) <= sf.LIMITE_DESCRICAO and d.endswith("…") and not d.endswith("Palav…")


def test_descricao_ignora_titulos_listas_e_credito():
    html = "<p><strong>LEAD:</strong> Festival de jazz chega a Americana em abril, com entrada gratuita no parque e shows ao vivo todos os dias.</p><h2>Serviço</h2><ul><li>Onde: parque</li></ul><p><em>Texto: fulano. Fotos: Divulgação</em></p>"
    d = sf.descricao_da_materia(html)
    assert d.startswith("Festival de jazz") and "Serviço" not in d and "Fotos" not in d


def test_titulo_seo_so_ganha_sufixo_se_couber():
    assert sf.titulo_seo("Festival de jazz em Americana") == "Festival de jazz em Americana • +blog"
    longo = "Prefeitura abre inscrições para curso gratuito de culinária em SBO"
    assert sf.titulo_seo(longo) == longo


def test_seo_da_agenda_e_fixo_e_usa_a_cidade():
    post = ar.montar_post_agenda(RELEASE)
    seo = sf.montar_seo(post, {}, post["_cidade"])
    assert seo["title"] == "Agenda cultural de novembro em Americana • +blog"
    assert seo["keyphrase"] == "agenda cultural americana"
    assert seo["description"].startswith("Veja a agenda cultural de novembro em Americana")
    assert 70 <= len(seo["description"]) <= sf.LIMITE_DESCRICAO


def test_palavra_chave_de_post_comum_leva_cidade():
    k = sf.palavra_chave("Festival de Jazz chega a Americana em abril", "Americana")
    assert k.endswith("americana") and "festival" in k and "jazz" in k
