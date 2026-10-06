"""
fact_check.py — Checagem factual da matéria contra o release (fonte da verdade).

Nenhuma camada usa LLM gerador:
  1. Código: datas, horários, valores (R$), telefones, links, e-mails, @perfis e
     gratuidade citados na matéria precisam existir no release.
  2. Jev (TypeSafe, via OpenRouter /api/alpha/decisions): cada frase da matéria é
     classificada contra o release — supported / contradicted / mixed /
     insufficient_evidence / opinion.

Fail-closed: frase que o Jev não conseguiu checar deixa o status "incompleto",
nunca "aprovado".

Uso CLI:
    python execution/fact_check.py --release-file release.txt --post-file post.json
    (post.json: titulo_site, subtitulo, resumo_telegram, html, texto_arte, legenda_curta)

Env vars:
    OPENROUTER_API_KEY — obrigatória
    JEV_MODEL          — opcional, padrão ~typesafe/jev-latest
    JEV_WORKERS        — opcional, padrão 6 (frases checadas em paralelo)
"""

import argparse
import html as _html
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from dotenv import load_dotenv

load_dotenv()

JEV_URL = "https://openrouter.ai/api/alpha/decisions"
LIMITE_RELEASE = 12000   # caracteres do release enviados ao Jev
LIMITE_FRASES = 80       # teto de frases por checagem (latência)
RISCO_BLOQUEIO = 0.6     # soma das probabilidades ruins que bloqueia
RISCO_ALERTA = 0.3       # soma que só gera alerta no card

# Campos que corrigir_texto (editorial.py) sabe reescrever.
CAMPOS_CORRIGIVEIS = ("titulo_site", "subtitulo", "resumo_telegram", "html")


# ─── Texto ────────────────────────────────────────────────────────────────────────────────

def texto_limpo(texto: str) -> str:
    """Remove tags HTML e entidades, colapsa espaços."""
    sem_tags = re.sub(r"<[^>]+>", " ", texto or "")
    return re.sub(r"\s+", " ", _html.unescape(sem_tags)).strip()


def html_para_blocos(html: str) -> list[str]:
    """Quebra o HTML em blocos de texto (um por <p>, <li>, <h2>...), sem tags."""
    partes = re.split(r"</(?:p|li|h[1-6]|blockquote)>|<br\s*/?>", html or "", flags=re.I)
    return [t for t in (texto_limpo(p) for p in partes) if t]


_RE_FIM_FRASE = re.compile(r"(?<=[.!?…])\s+(?=[\"“(A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9])")
_ABREVIACOES = {"av", "r", "dr", "dra", "sr", "sra", "prof", "profa", "nº", "n", "pça", "tel", "aprox", "jd"}


def dividir_frases(texto: str) -> list[str]:
    """Divide em frases sem quebrar em abreviações comuns (Av., Dr., nº.)."""
    frases: list[str] = []
    for pedaco in _RE_FIM_FRASE.split(texto or ""):
        pedaco = pedaco.strip()
        if not pedaco:
            continue
        if frases:
            ultima_palavra = frases[-1].rsplit(" ", 1)[-1].rstrip(".").lower()
            if ultima_palavra in _ABREVIACOES or re.fullmatch(r"[A-Z]\.", frases[-1].rsplit(" ", 1)[-1]):
                frases[-1] = f"{frases[-1]} {pedaco}"
                continue
        frases.append(pedaco)
    return frases


# ─── Camada 1: entidades por código ───────────────────────────────────────────────────

_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
          "agosto", "setembro", "outubro", "novembro", "dezembro"]

_RE_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_RE_URL = re.compile(
    r"(?:https?://|www\.)[^\s<>\"')]+"
    r"|\b[\w-]+(?:\.[\w-]+)*\.(?:com|org|net|gov|art|br)(?:\.br)?(?:/[^\s<>\"')]*)?",
    re.I,
)
_RE_PERFIL = re.compile(r"(?<![\w@.])@([A-Za-z0-9_.]{1,29}[A-Za-z0-9_])")
_RE_DATA_EXTENSO = re.compile(
    r"\b(\d{1,2}[º°]?(?:\s*(?:,|e|a|até|-)\s*\d{1,2}[º°]?)*)\s+de\s+"
    r"(janeiro|fevereiro|mar[çc]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\b",
    re.I,
)
_RE_DATA_BARRA = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/\d{2,4})?\b")
_RE_DIA_AVULSO = re.compile(r"\((\d{1,2})\)(?!\s*\d)|\bdias?\s+(\d{1,2})\b", re.I)
_RE_HORA_H = re.compile(r"\b(\d{1,2})\s?h(?:(\d{2})\b|\b)", re.I)
_RE_HORA_PONTOS = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_RE_VALOR = re.compile(
    r"R\$\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?"
    r"(?:\s*(mil|milh(?:ão|ões|ao|oes)|bilh(?:ão|ões|ao|oes))\b)?",
    re.I,
)
_RE_TELEFONE = re.compile(r"(?:\(?\b\d{2}\)?[\s.-]*)?\b(\d{4,5})[\s.-]?(\d{4})\b")
_RE_GRATUITO = re.compile(
    r"\b(gratuit[oa]s?|gratuitamente|gr[aá]tis|entrada (?:franca|livre)|sem custo|de graça)\b", re.I
)
_MULTIPLICADOR = {"mil": 1_000, "milh": 1_000_000, "bilh": 1_000_000_000}


def _num_mes(nome: str) -> int:
    return _MESES.index(nome.lower().replace("marco", "março")) + 1


def _normalizar_link(url: str) -> str:
    url = re.sub(r"^(?:https?://)?(?:www\.)?", "", url.lower())
    return url.rstrip(".,;:!?/")


def extrair_entidades(texto: str) -> dict[str, set]:
    """Extrai dados verificáveis de um texto já limpo (sem HTML)."""
    ent: dict[str, set] = {k: set() for k in
                           ("datas", "horarios", "valores", "telefones", "links", "emails", "perfis", "gratuito")}

    ent["emails"] = {e.lower() for e in _RE_EMAIL.findall(texto)}
    resto = _RE_EMAIL.sub(" ", texto)
    ent["links"] = {_normalizar_link(u) for u in _RE_URL.findall(resto)}
    resto = _RE_URL.sub(" ", resto)
    ent["perfis"] = {p.lower() for p in _RE_PERFIL.findall(resto)}

    for m in _RE_DATA_EXTENSO.finditer(resto):
        mes = _num_mes(m.group(2))
        for dia in re.findall(r"\d{1,2}", m.group(1)):
            if 1 <= int(dia) <= 31:
                ent["datas"].add((int(dia), mes))
    for d, mth in _RE_DATA_BARRA.findall(resto):
        if 1 <= int(d) <= 31 and 1 <= int(mth) <= 12:
            ent["datas"].add((int(d), int(mth)))
    for a, b in _RE_DIA_AVULSO.findall(resto):
        dia = int(a or b)
        if 1 <= dia <= 31:
            ent["datas"].add((dia, None))
    # "dia 5 de maio" gera (5, None) e (5, 5): fica só a forma com mês
    dias_com_mes = {d for d, m in ent["datas"] if m}
    ent["datas"] = {(d, m) for d, m in ent["datas"] if m or d not in dias_com_mes}

    for h, mi in _RE_HORA_H.findall(resto):
        if int(h) <= 24 and (not mi or int(mi) < 60):
            ent["horarios"].add(int(h) * 60 + int(mi or 0))
    for h, mi in _RE_HORA_PONTOS.findall(resto):
        if int(h) <= 24 and int(mi) < 60:
            ent["horarios"].add(int(h) * 60 + int(mi))

    for inteiro, cent, mult in _RE_VALOR.findall(resto):
        valor = int(inteiro.replace(".", "")) * 100 + int((cent or "0").ljust(2, "0"))
        if mult:
            valor *= _MULTIPLICADOR["mil" if mult.lower() == "mil" else mult.lower()[:4]]
        ent["valores"].add(valor)

    for bloco1, bloco2 in _RE_TELEFONE.findall(resto):
        if len(bloco1) == 4 and 1900 <= int(bloco1) <= 2100 and 1900 <= int(bloco2) <= 2100:
            continue  # "2025-2026" é intervalo de anos, não telefone
        ent["telefones"].add(bloco1[-4:] + bloco2)

    if _RE_GRATUITO.search(resto):
        ent["gratuito"].add(True)
    return ent


def _fmt_data(dia: int, mes: int | None) -> str:
    return f"{dia:02d}/{mes:02d}" if mes else f"dia {dia}"


def checar_entidades(release: str, campos: dict[str, str]) -> list[dict]:
    """
    Compara os dados de cada campo da matéria com os do release.
    release: texto limpo. campos: nome_do_campo → texto limpo.
    Retorna lista de bloqueantes {"campo", "trecho", "motivo", "origem": "codigo"}.
    """
    rel = extrair_entidades(release)
    dias_release = {d for d, _ in rel["datas"]}
    problemas: list[dict] = []

    def _add(campo: str, trecho: str, motivo: str) -> None:
        item = {"campo": campo, "trecho": trecho, "motivo": motivo, "origem": "codigo"}
        if item not in problemas:
            problemas.append(item)

    for campo, texto in campos.items():
        art = extrair_entidades(texto)
        for dia, mes in sorted(art["datas"], key=lambda x: (x[0], x[1] or 0)):
            ok = (dia, mes) in rel["datas"] or (dia, None) in rel["datas"] or (mes is None and dia in dias_release)
            if not ok:
                _add(campo, _fmt_data(dia, mes), "data não consta no release")
        for minutos in sorted(art["horarios"] - rel["horarios"]):
            _add(campo, f"{minutos // 60:02d}h{minutos % 60:02d}", "horário não consta no release")
        for centavos in sorted(art["valores"] - rel["valores"]):
            valor_br = f"{centavos / 100:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
            _add(campo, f"R$ {valor_br}", "valor não consta no release")
        for tel in sorted(art["telefones"] - rel["telefones"]):
            _add(campo, tel, "telefone não consta no release")
        for link in sorted(art["links"]):
            if not any(r.startswith(link) for r in rel["links"]):
                _add(campo, link, "link não consta no release")
        for email in sorted(art["emails"] - rel["emails"]):
            _add(campo, email, "e-mail não consta no release")
        for perfil in sorted(art["perfis"] - rel["perfis"]):
            _add(campo, f"@{perfil}", "perfil não consta no release")
        if art["gratuito"] and not rel["gratuito"]:
            _add(campo, "gratuito", "release não diz que é gratuito")
    return problemas


# ─── Camada 2: Jev frase a frase ────────────────────────────────────────────────────────

_PERGUNTA_JEV = {
    "verdict": {
        "type": "choice",
        "instructions": "Decide whether the claim (Brazilian Portuguese) is backed by the press release, "
                        "which is the only source of truth. Dates, times, prices, places and names must match exactly.",
        "criteria": {
            "supported": "Every fact in the claim is stated in the release.",
            "contradicted": "At least one fact in the claim conflicts with the release.",
            "mixed": "Part of the claim is backed and part conflicts with the release.",
            "insufficient_evidence": "The claim states a concrete fact (event, number, date, service, person, "
                                     "action) that the release does not mention.",
            "opinion": "The claim is only editorial opinion, invitation or framing, with no concrete verifiable fact.",
        },
    }
}

_MOTIVOS_JEV = {
    "contradicted": "contradiz o release",
    "mixed": "parte da frase contradiz o release",
    "insufficient_evidence": "informação que não está no release",
}


def jev_classificar(release: str, frase: str) -> dict:
    """
    Classifica uma frase contra o release via Jev.
    Retorna {"choice": str, "probabilities": dict, "cost": float}.
    Tenta 2 vezes (erro de rede, 429 ou 5xx); depois levanta a exceção.
    """
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY não configurada")
    payload = {
        "model": os.getenv("JEV_MODEL", "~typesafe/jev-latest"),
        "state": {"release": release, "claim": frase},
        "questions": _PERGUNTA_JEV,
    }
    ultimo_erro: Exception = RuntimeError("Jev sem resposta")
    for tentativa in range(2):
        try:
            r = requests.post(JEV_URL, headers={"Authorization": f"Bearer {key}"}, json=payload, timeout=30)
            if r.status_code == 200:
                body = r.json()
                v = body["answers"]["verdict"]
                return {
                    "choice": v["choice"],
                    "probabilities": v.get("probabilities") or {v["choice"]: v.get("confidence", 1.0)},
                    "cost": float((body.get("usage") or {}).get("cost", 0.0)),
                }
            ultimo_erro = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
            if r.status_code != 429 and r.status_code < 500:
                break  # erro do nosso lado (auth, payload): não adianta repetir
        except (requests.RequestException, KeyError, ValueError) as e:
            ultimo_erro = e
        if tentativa == 0:
            time.sleep(2)
    raise ultimo_erro


def _risco(classificacao: dict) -> tuple[float, str]:
    """Soma das probabilidades ruins e o veredito ruim mais provável."""
    probs = classificacao["probabilities"]
    ruins = {k: float(probs.get(k, 0) or 0) for k in _MOTIVOS_JEV}
    pior = max(ruins, key=ruins.get)
    return sum(ruins.values()), pior


def campos_do_post(post: dict, legenda: str = "") -> dict[str, str]:
    """Textos limpos de cada campo que vai ao leitor."""
    arte = post.get("texto_arte") or {}
    arte_txt = ". ".join(t for t in (arte.get("titulo_principal", ""), arte.get("linha_apoio", "")) if t)
    return {
        "titulo_site": texto_limpo(post.get("titulo_site", "")),
        "subtitulo": texto_limpo(post.get("subtitulo", "")),
        "resumo_telegram": texto_limpo(post.get("resumo_telegram", "")),
        "html": " ".join(html_para_blocos(post.get("html", ""))),
        "arte": texto_limpo(arte_txt),
        "legenda": texto_limpo(re.sub(r"#\w+", " ", legenda or "")),
    }


def _frase_checavel(frase: str, min_palavras: int) -> bool:
    return len(frase.split()) >= min_palavras and "[DADO AUSENTE" not in frase.upper()


def frases_para_checar(post: dict, campos: dict[str, str]) -> list[tuple[str, str]]:
    """Lista (campo, frase) sem repetição. HTML é dividido por bloco para não colar itens de lista."""
    itens: list[tuple[str, str]] = []
    for bloco in html_para_blocos(post.get("html", "")):
        itens += [("html", f) for f in dividir_frases(bloco) if _frase_checavel(f, 3)]
    for campo in ("titulo_site", "subtitulo", "resumo_telegram", "arte", "legenda"):
        itens += [(campo, f) for f in dividir_frases(campos[campo]) if _frase_checavel(f, 2)]
    vistos: set[str] = set()
    unicos = []
    for campo, frase in itens:
        if frase.lower() not in vistos:
            vistos.add(frase.lower())
            unicos.append((campo, frase))
    return unicos


def verificar_post(release: str, post: dict, legenda: str = "") -> dict:
    """
    Checa a matéria inteira contra o release.
    Retorna {
      "status": "aprovado" | "bloqueado" | "incompleto",
      "bloqueantes": [{"campo", "trecho", "motivo", "origem"}],
      "alertas":     [{"campo", "trecho", "motivo", "origem"}],
      "frases_checadas": int, "nao_checadas": int, "custo_usd": float,
    }
    """
    release_limpo = texto_limpo(release)
    campos = campos_do_post(post, legenda)
    bloqueantes = checar_entidades(release_limpo, campos)
    alertas: list[dict] = []
    if len(release_limpo) > LIMITE_RELEASE:
        alertas.append({"campo": "release", "trecho": "",
                        "motivo": f"release longo: Jev leu só os primeiros {LIMITE_RELEASE} caracteres",
                        "origem": "jev"})

    frases = frases_para_checar(post, campos)
    nao_checadas = max(0, len(frases) - LIMITE_FRASES)
    frases = frases[:LIMITE_FRASES]
    if not frases:
        alertas.append({"campo": "html", "trecho": "", "motivo": "nenhuma frase para checar", "origem": "jev"})

    def _uma(item: tuple[str, str]):
        campo, frase = item
        try:
            return campo, frase, jev_classificar(release_limpo[:LIMITE_RELEASE], frase)
        except Exception as e:
            print(f"[fact_check] Jev falhou em '{frase[:50]}': {e}", file=sys.stderr)
            return campo, frase, None

    with ThreadPoolExecutor(max_workers=int(os.getenv("JEV_WORKERS", "6"))) as ex:
        resultados = list(ex.map(_uma, frases))

    custo, checadas = 0.0, 0
    for campo, frase, cls in resultados:
        if cls is None:
            nao_checadas += 1
            continue
        checadas += 1
        custo += cls["cost"]
        risco, pior = _risco(cls)
        item = {"campo": campo, "trecho": frase, "motivo": _MOTIVOS_JEV[pior], "origem": "jev"}
        if risco >= RISCO_BLOQUEIO:
            bloqueantes.append(item)
        elif risco >= RISCO_ALERTA:
            alertas.append(item)

    if bloqueantes:
        status = "bloqueado"
    elif nao_checadas or not frases:
        status = "incompleto"
    else:
        status = "aprovado"
    return {
        "status": status,
        "bloqueantes": bloqueantes,
        "alertas": alertas,
        "frases_checadas": checadas,
        "nao_checadas": nao_checadas,
        "custo_usd": round(custo, 6),
    }


def linha_card(checagem: dict) -> str:
    """Linha de status da checagem para o card do Telegram (texto puro, sem escape)."""
    status = checagem.get("status")
    if status == "aprovado":
        n_alertas = len(checagem.get("alertas") or [])
        extra = f" · {n_alertas} alerta(s)" if n_alertas else ""
        return f"✅ Checagem: {checagem.get('frases_checadas', 0)} frases conferidas com o release{extra}"
    if status == "bloqueado":
        return (f"⛔ Checagem: {len(checagem.get('bloqueantes') or [])} problema(s) não corrigido(s)"
                " — revise antes de publicar")
    if status == "incompleto":
        return f"⚠️ Checagem incompleta: {checagem.get('nao_checadas', 0)} frase(s) não conferida(s)"
    return "⚠️ Checagem não rodou"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Checa matéria contra release (código + Jev)")
    parser.add_argument("--release-file", required=True, help="Arquivo .txt com o release")
    parser.add_argument("--post-file", required=True, help="JSON com campos do post (+ legenda_curta opcional)")
    args = parser.parse_args()

    with open(args.release_file, encoding="utf-8") as f:
        release = f.read()
    with open(args.post_file, encoding="utf-8") as f:
        post = json.load(f)
    resultado = verificar_post(release, post, post.get("legenda_curta", ""))
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    sys.exit(0 if resultado["status"] == "aprovado" else 1)


if __name__ == "__main__":
    main()
