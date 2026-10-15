"""Testa o filtro que remove frases sobre o que NÃO se sabe (lacunas e especulação)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "execution"))

import text_guard as tg

FRASE_DO_USUARIO = ("Embora os detalhes específicos das atrações não tenham sido divulgados, a expectativa é de "
                    "que haja opções variadas para entreter os visitantes, desde brincadeiras a atividades culturais.")


def test_remove_a_frase_reportada_pelo_usuario():
    html = f"<p>A feira acontece no sábado, no centro. {FRASE_DO_USUARIO}</p>"
    novo, removidas = tg.limpar_html(html)
    assert novo == "<p>A feira acontece no sábado, no centro.</p>"
    assert len(removidas) == 1 and "Embora os detalhes" in removidas[0]


def test_remove_varias_formas_de_dizer_que_nao_se_sabe():
    frases = [
        "Os detalhes da programação ainda não foram divulgados.",
        "A programação completa ainda será divulgada.",
        "Mais informações serão divulgadas em breve.",
        "Os organizadores não informaram o horário.",
        "Não há informações sobre valores.",
        "Não foi informado se haverá estacionamento.",
        "Ainda não há confirmação das atrações.",
        "Não se sabe quais artistas vão se apresentar.",
        "Os valores ainda serão definidos.",
        "Segue sem detalhes sobre o cardápio.",
    ]
    for f in frases:
        novo, removidas = tg.limpar_html(f"<p>O evento é no sábado. {f}</p>")
        assert novo == "<p>O evento é no sábado.</p>", f
        assert removidas == [f], f


def test_nao_remove_frases_normais_mesmo_com_negacao():
    boas = [
        "A entrada é gratuita.",
        "O evento não terá custo para o público.",
        "Os ingressos não estarão à venda no local.",
        "A programação inclui oficinas, shows e contação de histórias.",
        "Não é necessário fazer inscrição.",
        "O estacionamento não é cobrado.",
        "“Ainda não tivemos um evento desse tamanho”, disse o secretário.",
    ]
    for f in boas:
        html = f"<p>{f}</p>"
        novo, removidas = tg.limpar_html(html)
        assert novo == html, f
        assert removidas == [], f


def test_remove_o_paragrafo_quando_so_sobra_lacuna():
    html = "<p>Abertura às 9h.</p><p>Os detalhes ainda não foram divulgados.</p><p>Entrada gratuita.</p>"
    novo, removidas = tg.limpar_html(html)
    assert novo == "<p>Abertura às 9h.</p><p>Entrada gratuita.</p>"
    assert len(removidas) == 1


def test_remove_item_de_lista_com_lacuna():
    html = "<ul><li><strong>Quando:</strong> sábado, 9h</li><li><strong>Valor:</strong> não foi informado</li></ul>"
    novo, _ = tg.limpar_html(html)
    assert novo == "<ul><li><strong>Quando:</strong> sábado, 9h</li></ul>"


def test_preserva_tags_nas_frases_que_ficam():
    html = "<p>A <strong>Feira do Produtor</strong> volta em outubro. Os preços não foram divulgados.</p>"
    novo, _ = tg.limpar_html(html)
    assert novo == "<p>A <strong>Feira do Produtor</strong> volta em outubro.</p>"


def test_nao_remove_frase_com_tag_aberta_e_fechada_em_frases_diferentes():
    html = "<p><strong>Atenção. Os detalhes não foram divulgados.</strong> Chegue cedo.</p>"
    novo, removidas = tg.limpar_html(html)
    assert novo == html  # remover quebraria o <strong>
    assert removidas == []


def test_html_vazio_ou_sem_blocos():
    assert tg.limpar_html("") == ("", [])
    assert tg.limpar_html("texto solto sem tags") == ("texto solto sem tags", [])


def test_limpar_texto_remove_frases_da_legenda():
    texto = "Tem feira no sábado.\n\nOs detalhes ainda não foram divulgados.\n\nVai ser bom."
    novo, removidas = tg.limpar_texto(texto)
    assert novo == "Tem feira no sábado.\n\nVai ser bom."
    assert len(removidas) == 1


def test_limpar_texto_nao_mexe_em_texto_normal():
    texto = "Tem feira no sábado.\n\nA entrada é gratuita."
    assert tg.limpar_texto(texto) == (texto, [])
