"""
text_guard.py — Remove do texto as frases sobre o que NÃO se sabe.

O leitor não quer ler "os detalhes ainda não foram divulgados" nem "a expectativa é
de que haja...": se o release não diz, a matéria simplesmente não fala. O prompt já
pede isso ao redator; este filtro garante em código, mesmo quando o modelo escorrega.

Só remove frases que comentam a AUSÊNCIA de informação (não divulgado, não informado,
será divulgado em breve, não há detalhes...). Frases normais com negação
("o evento não terá custo", "não é necessário inscrição") ficam.
"""

import re

_PARTICIPIO = (r"(?:divulgad|informad|detalhad|confirmad|anunciad|revelad|especificad|"
               r"disponibilizad|definid|dispon[ií]ve)\w*")

# Cada padrão descreve um jeito de dizer "isso a gente não sabe".
_PADROES_LACUNA = [re.compile(p, re.I) for p in (
    # "não foram divulgados", "não tenham sido divulgados", "ainda não foi confirmado"
    rf"\bn[ãa]o\s+(?:foram?|tenham?|foi|ser(?:[áa]|[ãa]o)|est[ãa]o|est[áa]|h[áa]|houve|existem?)\s+"
    rf"(?:sido\s+)?(?:ainda\s+)?{_PARTICIPIO}",
    # "ainda será/serão divulgado(a)(s)", "serão divulgadas em breve"
    rf"\b(?:ainda\s+)?ser(?:[áa]|[ãa]o)\s+{_PARTICIPIO}",
    # "os organizadores não informaram o horário"
    r"\bn[ãa]o\s+(?:informaram|divulgaram|detalharam|confirmaram|especificaram|anunciaram|revelaram)\b",
    # "não há informações/detalhes/confirmação sobre..."
    r"\bn[ãa]o\s+h[áa]\s+(?:mais\s+|maiores\s+)?(?:informa[çc][õo]es|detalhes|confirma[çc][ãa]o|defini[çc][ãa]o)",
    # "ainda não há/foi/foram", "ainda não se sabe"
    r"\bainda\s+n[ãa]o\s+(?:h[áa]|se\s+sabe|existe)\b",
    r"\bn[ãa]o\s+se\s+sabe\b",
    # "sem detalhes", "sem maiores informações"
    r"\bsem\s+(?:maiores\s+|mais\s+)?(?:detalhes|informa[çc][õo]es)\b",
    # "a confirmar", "a ser divulgado"
    r"\ba\s+(?:ser\s+)?(?:confirmar|divulgar|definir|anunciar)\b",
)]

_RE_FIM_FRASE = re.compile(r"(?<=[.!?…])\s+(?=[\"“(<A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9])")
_RE_TAGS = re.compile(r"<[^>]+>")
_RE_BLOCO = re.compile(r"<(p|li)(\s[^>]*)?>(.*?)</\1>", re.I | re.S)
_TAGS_DE_FORMATO = ("strong", "em", "b", "i", "a", "u", "span")
_ABREVIACOES = {"av", "r", "dr", "dra", "sr", "sra", "prof", "profa", "nº", "n", "pça", "tel", "aprox", "jd"}


def _tem_lacuna(frase_html: str) -> bool:
    texto = _RE_TAGS.sub(" ", frase_html)
    return any(p.search(texto) for p in _PADROES_LACUNA)


def _tags_balanceadas(trecho: str) -> bool:
    """True se cada tag de formatação aberta no trecho também fecha nele."""
    for tag in _TAGS_DE_FORMATO:
        abre = len(re.findall(rf"<{tag}(?:\s[^>]*)?>", trecho, re.I))
        fecha = len(re.findall(rf"</{tag}>", trecho, re.I))
        if abre != fecha:
            return False
    return True


def _dividir(texto: str) -> list[str]:
    """Divide em frases sem quebrar em abreviações (Av., Dr., nº.)."""
    frases: list[str] = []
    for pedaco in _RE_FIM_FRASE.split(texto):
        if not pedaco.strip():
            continue
        if frases:
            ultima = _RE_TAGS.sub("", frases[-1]).rsplit(" ", 1)[-1].rstrip(".").lower()
            if ultima in _ABREVIACOES:
                frases[-1] = f"{frases[-1]} {pedaco}"
                continue
        frases.append(pedaco)
    return frases


def _limpar_trecho(trecho: str, removidas: list[str]) -> str:
    """Remove as frases com lacuna de um trecho (um parágrafo ou item). Devolve o que sobrou."""
    mantidas = []
    for frase in _dividir(trecho.strip()):
        if _tem_lacuna(frase) and _tags_balanceadas(frase):
            removidas.append(_RE_TAGS.sub("", frase).strip())
        else:
            mantidas.append(frase)
    return " ".join(mantidas)


def limpar_html(html: str) -> tuple[str, list[str]]:
    """
    Remove frases de lacuna dos <p> e <li> do HTML. Parágrafo ou item que ficar vazio é removido.
    Retorna (html_limpo, frases_removidas).
    """
    removidas: list[str] = []

    def _bloco(m: re.Match) -> str:
        tag, attrs, interno = m.group(1), m.group(2) or "", m.group(3)
        novo = _limpar_trecho(interno, removidas)
        return f"<{tag}{attrs}>{novo}</{tag}>" if _RE_TAGS.sub("", novo).strip() else ""

    return _RE_BLOCO.sub(_bloco, html or ""), removidas


def limpar_texto(texto: str) -> tuple[str, list[str]]:
    """Versão para texto puro (legenda, resumo): trabalha por parágrafo (linha em branco)."""
    removidas: list[str] = []
    paragrafos = []
    for par in (texto or "").split("\n\n"):
        novo = _limpar_trecho(par, removidas) if par.strip() else par
        if novo.strip():
            paragrafos.append(novo)
    return "\n\n".join(paragrafos), removidas
