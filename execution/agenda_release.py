"""
agenda_release.py — Release de AGENDA publicado na íntegra, montado por código (sem LLM).

Release de agenda (programação do mês, do fim de semana...) já vem estruturado: um
cabeçalho de data por bloco, seguido do que acontece naquele dia. Reescrever isso com
IA só gera risco (perda de item, dado trocado). Aqui o texto é parseado e o HTML é
montado em código, em ordem, com TODO bloco do release — nada é resumido nem inventado.

A IA continua entrando só onde não há risco factual (legenda do Instagram, arte).

Uso (pelo pipeline): eh_agenda(texto) -> bool;  montar_post_agenda(texto, ...) -> dict
"""

import html as _html
import re
from collections import Counter

MIN_BLOCOS = 5   # menos que isso não é agenda: segue o fluxo normal de reescrita

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]
CIDADES = ["Santa Bárbara d'Oeste", "Nova Odessa", "Americana", "Sumaré"]

# "04/11 (quarta-feira)", "04, 05 e 06 (quarta, quinta e sexta-feira)", "De 10 a 13/11 (...)", "De 23/11 a 11/12"
_RE_CAB_DATA = re.compile(r"^(?:De\s+)?\d{1,2}(?:[\s,/]|\be\b|\ba\b|\d)*(?:\([^)]*\))?\s*$", re.I)
_RE_CAB_RECORRENTE = re.compile(r"^(?:Todas\s+as|Todos\s+os)\s+[^.]{3,60}$", re.I)
_RE_RODAPE = re.compile(r"^(?:Texto|Créditos?|Fotos?|Foto)\b", re.I)
_RE_CONFIRA = re.compile(r"^Confira\b.{0,60}:?\s*$", re.I)
_RE_URL = re.compile(r"(?<![\w/@.])((?:https?://|www\.)[^\s<>\"“”,;)]+[^\s<>\"“”,;).])")
_RE_EMAIL = re.compile(r"(?<![\w.@/])([\w.+-]+@[\w-]+(?:\.[\w-]+)+)")


def _paragrafos(texto: str) -> list[str]:
    """Quebra o release em parágrafos (linha em branco separa); junta as linhas quebradas do e-mail."""
    texto = re.sub(r"\r+\n|\r", "\n", texto)   # e-mails reais chegam com \r\n e até \r\r\n
    blocos = re.split(r"\n\s*\n", texto.strip())
    return [re.sub(r"\s*\n\s*", " ", b).strip() for b in blocos if b.strip()]


def _eh_cabecalho(par: str) -> bool:
    if len(par) > 70 or "\n" in par:
        return False
    if re.search(r"\d{3,}", par):              # "03/11/2026" é a data de envio, não um bloco
        return False
    return bool(_RE_CAB_DATA.match(par) and re.search(r"\d", par)) or bool(_RE_CAB_RECORRENTE.match(par))


def parse_agenda(texto: str) -> dict:
    """
    Retorna {"titulo_release", "intro": [parágrafos], "blocos": [{"cabecalho", "textos": [..]}], "rodape": [..]}.
    O texto dos parágrafos é copiado como veio — só reflow das quebras de linha do e-mail.
    """
    pars = _paragrafos(texto)
    idx = [i for i, p in enumerate(pars) if _eh_cabecalho(p)]
    if not idx:
        return {"titulo_release": "", "intro": [], "blocos": [], "rodape": []}

    antes = pars[:idx[0]]
    titulo_release = ""
    if antes and not antes[0].rstrip().endswith((".", "!", "?", "”", '"')):
        titulo_release, antes = antes[0], antes[1:]
    intro = [p for p in antes if not _RE_CONFIRA.match(p)]

    blocos, rodape = [], []
    for n, i in enumerate(idx):
        fim = idx[n + 1] if n + 1 < len(idx) else len(pars)
        corpo = pars[i + 1:fim]
        # O rodapé (autor, crédito de fotos, data de envio) começa no primeiro parágrafo "Texto:/Créditos".
        corte = next((k for k, p in enumerate(corpo) if _RE_RODAPE.match(p)), None)
        if corte is not None:
            rodape = corpo[corte:]
            corpo = corpo[:corte]
            blocos.append({"cabecalho": pars[i], "textos": corpo})
            break
        blocos.append({"cabecalho": pars[i], "textos": corpo})
    return {"titulo_release": titulo_release, "intro": intro, "blocos": blocos, "rodape": rodape}


def eh_agenda(texto: str) -> bool:
    """True quando o release tem blocos de data suficientes para ser publicado como agenda."""
    return len(parse_agenda(texto)["blocos"]) >= MIN_BLOCOS


def mes_predominante(blocos: list[dict]) -> tuple[str, int]:
    """(nome_do_mes, numero) citado nos cabeçalhos tipo '04/11'. ('', 0) se não houver."""
    cont = Counter()
    for b in blocos:
        for m in re.findall(r"/(\d{1,2})\b", b["cabecalho"]):
            if 1 <= int(m) <= 12:
                cont[int(m)] += 1
    if not cont:
        return "", 0
    num = cont.most_common(1)[0][0]
    return MESES[num - 1], num


def _linkar(texto: str) -> str:
    """Escapa o texto e transforma sites e e-mails em links."""
    seguro = _html.escape(texto, quote=False)

    def _url(m):
        u = m.group(1)
        href = u if u.lower().startswith("http") else f"https://{u}"
        return f'<a href="{href}" target="_blank" rel="noopener">{u}</a>'

    seguro = _RE_URL.sub(_url, seguro)
    # e-mails fora de links já criados
    partes = re.split(r"(<a [^>]*>.*?</a>)", seguro)
    for i in range(0, len(partes), 2):
        partes[i] = _RE_EMAIL.sub(lambda m: f'<a href="mailto:{m.group(1)}">{m.group(1)}</a>', partes[i])
    return "".join(partes)


def renderizar_html(parsed: dict, aviso: str = "") -> str:
    """HTML puro: introdução do release + 'Programação completa' com um bloco por data."""
    out = [f"<p>{_linkar(p)}</p>" for p in parsed["intro"]]
    out.append("<h2>Programação completa</h2>")
    anterior = None
    for b in parsed["blocos"]:
        if b["cabecalho"] != anterior:        # datas iguais em sequência dividem o mesmo título
            out.append(f"<h3>{_html.escape(b['cabecalho'], quote=False)}</h3>")
        anterior = b["cabecalho"]
        out.extend(f"<p>{_linkar(t)}</p>" for t in b["textos"])
    autoria = next((p for p in parsed["rodape"] if re.match(r"^Texto\s*:", p, re.I)), "")
    rodape = [x for x in (aviso, autoria) if x]
    if rodape:
        out.append("<p><em>" + " ".join(_html.escape(x, quote=False) for x in rodape) + "</em></p>")
    return "\n".join(out)


def cidade_da_agenda(texto: str, fatos: dict | None = None) -> str:
    """Cidade da agenda: a mais citada no release entre as quatro do portal."""
    cont = {c: len(re.findall(re.escape(c), texto, re.I)) for c in CIDADES}
    melhor = max(cont, key=cont.get)
    if cont[melhor]:
        return melhor
    return (fatos or {}).get("cidade", "") or "Americana"


def _slug(texto: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def montar_post_agenda(texto: str, fatos: dict | None = None, sender: str = "") -> dict:
    """
    Monta o dict `post` (mesmo formato de editorial.gerar_conteudo) para uma agenda.
    Título, slug, resumo e HTML saem do release por regra — sem LLM.
    """
    parsed = parse_agenda(texto)
    mes, _ = mes_predominante(parsed["blocos"])
    cidade = cidade_da_agenda(texto, fatos)
    instituicao = ((fatos or {}).get("instituicao_realizadora") or "").strip()
    if instituicao:
        aviso = f"Informações enviadas por {instituicao} e publicadas na íntegra pelo +blog."
    else:
        aviso = "Informações recebidas por release e publicadas na íntegra pelo +blog."

    de_mes = f"de {mes} " if mes else ""
    titulo = f"Agenda cultural {de_mes}em {cidade}".replace("  ", " ")
    slug = _slug(f"agenda cultural {mes} {cidade}")
    n = len(parsed["blocos"])
    resumo = (f"Agenda {de_mes}em {cidade} publicada na íntegra, como veio no release: "
              f"{n} datas/períodos, com horários, locais e ingressos de cada atração.")
    return {
        "titulo_site": titulo,
        "titulo_social": titulo,
        "subtitulo": "",
        "slug": slug,
        "categoria": "Rolês",
        "wp_category_id": 19,
        "tags": [t for t in (cidade.lower(), "agenda cultural", mes, "cultura") if t],
        "resumo_telegram": resumo,
        "html": renderizar_html(parsed, aviso),
        "texto_arte": {
            "template": "ameriafro_v3",
            "badge": "AGENDA",
            "titulo_principal": f"Agenda cultural {de_mes}".strip().capitalize() if mes else "Agenda cultural",
            "linha_apoio": f"Programação completa em {cidade}"[:60],
            "alerta": "",
        },
        "creditos_wordpress": {
            "texto": "release publicado na íntegra pelo +blog",
            "fotos": (fatos or {}).get("creditos_fotos") or "Divulgação",
            "usar_apenas_no_html_wordpress": True,
        },
        "_agenda_integra": True,
        "_cidade": cidade,
        "_blocos": n,
    }
