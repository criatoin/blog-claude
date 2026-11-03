"""
seo_fields.py — Campos de SEO (All in One SEO) montados por regra, sem LLM.

Título SEO, meta description e palavra-chave de foco saem do que a matéria JÁ diz
(título, abertura, cidade), então não há como inventar dado novo. A descrição é cortada
em limite de frase/palavra, nunca no meio de uma palavra.
"""

import html as _html
import re

SUFIXO = " • +blog"
LIMITE_TITULO = 60        # Google corta ~60 caracteres
LIMITE_DESCRICAO = 155    # Google corta ~155-160
MIN_DESCRICAO = 100

_STOP = {"a", "o", "as", "os", "um", "uma", "de", "da", "do", "das", "dos", "e", "em", "no", "na", "nos", "nas",
         "para", "com", "por", "que", "tem", "traz", "chega", "ao", "à", "aos", "se"}
_RE_FIM_FRASE = re.compile(r"(?<=[.!?])\s+(?=[\"“(A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9])")


def _texto(html: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def _abertura(html: str) -> str:
    """Texto dos parágrafos <p> (sem títulos nem listas), sem o rótulo 'LEAD:'."""
    pars = re.findall(r"<p(?:\s[^>]*)?>(.*?)</p>", html, re.I | re.S)
    pars = [_texto(p) for p in pars]
    pars = [re.sub(r"^LEAD:\s*", "", p, flags=re.I) for p in pars if p and not p.lower().startswith("texto:")]
    return " ".join(pars)


def descricao_da_materia(html: str, limite: int = LIMITE_DESCRICAO) -> str:
    """Primeiras frases da matéria que cabem no limite; se a 1ª já passa, corta na última palavra inteira."""
    texto = _abertura(html)
    if not texto:
        return ""
    frases = _RE_FIM_FRASE.split(texto)
    desc = ""
    for f in frases:
        candidato = f"{desc} {f}".strip()
        if len(candidato) <= limite:
            desc = candidato
        else:
            break
    if desc and (len(desc) >= MIN_DESCRICAO or desc == texto):
        return desc
    # 1ª frase maior que o limite, ou curta demais e a próxima não coube: corta na última palavra inteira
    corte = texto[:limite - 1].rsplit(" ", 1)[0].rstrip(" ,;:-–—")
    return corte + "…"


def titulo_seo(titulo: str) -> str:
    """Título + ' • +blog' se couber em 60 caracteres; senão só o título."""
    titulo = titulo.strip()
    return titulo + SUFIXO if len(titulo) + len(SUFIXO) <= LIMITE_TITULO else titulo


def palavra_chave(titulo: str, cidade: str = "", agenda: bool = False) -> str:
    """Frase-chave de foco: 'agenda cultural <cidade>' ou as 3 primeiras palavras relevantes do título + cidade."""
    cidade_l = cidade.strip().lower()
    if agenda:
        return f"agenda cultural {cidade_l}".strip()
    palavras = [p for p in re.findall(r"[\wÀ-ÿ'-]+", titulo.lower())
                if p not in _STOP and not p.isdigit() and p not in cidade_l.split()]
    base = " ".join(palavras[:3])
    return f"{base} {cidade_l}".strip()


def montar_seo(post: dict, fatos: dict | None = None, cidade: str = "") -> dict:
    """
    Retorna {"title", "description", "keyphrase", "excerpt"} para o post (dict de gerar_conteudo
    ou de agenda_release.montar_post_agenda).
    """
    fatos = fatos or {}
    cidade = cidade or fatos.get("cidade", "")
    titulo = post.get("titulo_site", "")
    agenda = bool(post.get("_agenda_integra"))
    if agenda:
        mes = next((t for t in post.get("tags", []) if t in
                    ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
                     "setembro", "outubro", "novembro", "dezembro")), "")
        de_mes = f" de {mes}" if mes else ""
        desc = (f"Veja a agenda cultural{de_mes} em {cidade}, com datas, horários, locais e ingressos de cada "
                f"evento.").replace("  ", " ")
    else:
        desc = descricao_da_materia(post.get("html", ""))
    return {
        "title": titulo_seo(titulo),
        "description": desc,
        "keyphrase": palavra_chave(titulo, cidade, agenda),
        "excerpt": desc,
    }
