"""
run_pauta_generate.py — Pautas semanais 100% baseadas em fontes reais (search-first).

Fluxo:
  1. Coleta determinística: queries fixas no Tavily (últimos 7 dias, região)
  2. Curadoria via modelo criativo: agrupa achados em até 10 pautas com fontes
  3. Validação determinística: pauta sem fonte real coletada = descartada
  4. Salva .tmp/pautas_semana.json + envia lista ao Telegram com links das fontes
  5. GSC/GA entram apenas como critério de priorização

Uso:
    python execution/run_pauta_generate.py
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
PAUTAS_FILE = PROJECT_DIR / ".tmp" / "pautas_semana.json"

# Queries fixas — cobertura das 4 cidades + agenda regional
QUERIES = [
    "agenda cultural Americana SP esta semana",
    "eventos fim de semana Americana SP",
    "agenda cultural Santa Bárbara d'Oeste",
    "eventos Santa Bárbara d'Oeste esta semana",
    "eventos culturais Nova Odessa SP",
    "o que fazer Nova Odessa fim de semana",
    "programação cultural Sumaré SP",
    "eventos Sumaré esta semana",
    "shows teatro região de Americana Campinas",
    "cursos oficinas gratuitas Americana Santa Bárbara",
]


def _run_json(args: list[str]) -> dict | list | None:
    result = subprocess.run(
        ["python"] + args, capture_output=True, text=True,
        encoding="utf-8", errors="replace", cwd=str(PROJECT_DIR),
    )
    if result.returncode != 0:
        print(f"[pauta_gen] Aviso em {Path(args[0]).name}:\n{result.stderr[:500]}", file=sys.stderr)
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def coletar_achados() -> list[dict]:
    """Roda todas as queries no Tavily e deduplica por URL."""
    achados: dict[str, dict] = {}
    for q in QUERIES:
        print(f"[pauta_gen] Buscando: '{q}'...", file=sys.stderr)
        result = _run_json([str(SCRIPT_DIR / "search_sources.py"),
                            "--query", q, "--max", "5", "--days", "7"])
        if not result:
            continue
        for s in result.get("sources", []):
            url = s.get("url", "")
            if url and url not in achados:
                achados[url] = s
    print(f"[pauta_gen] {len(achados)} achado(s) único(s).", file=sys.stderr)
    return list(achados.values())


def curar_pautas(achados: list[dict], gsc_ctx: str, ga_ctx: str) -> list[dict]:
    """Modelo criativo agrupa achados reais em até 10 pautas com fontes citadas."""
    sys.path.insert(0, str(SCRIPT_DIR))
    from llm_call import llm_call_json, creative_model

    achados_texto = "\n".join(
        f"[{i+1}] {a.get('title','')} — {a.get('url','')}\n    {a.get('snippet','')[:280]}"
        for i, a in enumerate(achados)
    )
    prioridade = ""
    if gsc_ctx:
        prioridade += f"\n\n{gsc_ctx}"
    if ga_ctx:
        prioridade += f"\n\n{ga_ctx}"

    system = """Você é o editor-chefe do +blog, portal de cultura e diversão de Americana, Santa Bárbara d'Oeste (SBO), Nova Odessa e Sumaré (região de Campinas, SP).

Você receberá ACHADOS REAIS da web (título, URL, trecho). Sua tarefa é agrupá-los em até 10 sugestões de pauta para a semana.

REGRAS ABSOLUTAS:
- Cada pauta DEVE citar em "fontes" as URLs exatas dos achados que a embasam (copie a URL literal).
- Só afirme o que está nos trechos. NUNCA invente evento, data, local ou atração.
- Se um achado não tem relação com cultura/diversão nas 4 cidades, ignore-o.
- Se os achados não renderem 10 pautas, retorne menos. Qualidade > quantidade.
- Máx 3 pautas do mesmo tipo (Agenda|Lista|Explicativa|Retrospectiva|Antevisão).
- Título SEO: máx 65 chars, cidade + tema principal.
- Use os dados de priorização (GSC/GA), se presentes, para ordenar por potencial de busca.

Categorias WordPress:
Música: 23 | Arte: 22 | Audiovisual: 533 | Literatura: 540 | Educação: 384
Diversão: 11 | Cultura: 13 | Rolês: 19 | Comida: 10 | Eventos: 12

Retorne APENAS JSON:
{"pautas": [{
  "titulo": "...",
  "keyword": "...",
  "categoria": "...",
  "wp_category_id": 19,
  "justificativa": "...",
  "tipo": "Agenda|Lista|Explicativa|Retrospectiva|Antevisão",
  "fontes": ["url1", "url2"]
}]}"""

    hoje = datetime.now().strftime("Semana de %d/%m/%Y")
    user = f"{hoje}\n\nACHADOS REAIS DA WEB:\n{achados_texto}{prioridade}"

    try:
        resultado = llm_call_json(system=system, user=user, model=creative_model())
        if isinstance(resultado, dict):
            return resultado.get("pautas", [])
        if isinstance(resultado, list):
            return resultado
        return []
    except Exception as e:
        print(f"[pauta_gen] Erro na curadoria: {e}", file=sys.stderr)
        return []


def validar_pautas(pautas: list[dict], urls_validas: set[str]) -> list[dict]:
    """Anti-alucinação: remove URLs inventadas e descarta pautas sem fonte real."""
    aprovadas = []
    for p in pautas:
        fontes_ok = [u for u in p.get("fontes", []) if u in urls_validas]
        if not fontes_ok:
            print(f"[pauta_gen] DESCARTADA (sem fonte real): {p.get('titulo','')[:60]}", file=sys.stderr)
            continue
        p["fontes"] = fontes_ok
        aprovadas.append(p)
    return aprovadas


def _tentar_contexto(script: str, label: str, formato) -> str:
    data = _run_json([str(SCRIPT_DIR / script)])
    if not data:
        print(f"[pauta_gen] {label} indisponível.", file=sys.stderr)
        return ""
    return formato(data)


def main() -> None:
    print("[pauta_gen] Gerando pautas da semana (search-first)...", file=sys.stderr)

    # 1. Coleta real
    achados = coletar_achados()
    if not achados:
        subprocess.run(["python", str(SCRIPT_DIR / "telegram_notify.py"), "send-text",
                        "--message", "⚠️ Pautas da semana: nenhuma fonte encontrada na web. "
                                     "Sem pautas confiáveis para sugerir."],
                       cwd=str(PROJECT_DIR))
        sys.exit(0)

    # 2. Priorização (opcional)
    def _fmt_gsc(data):
        linhas = ["Dados GSC (queries com volume, para priorizar):"]
        items = data if isinstance(data, list) else data.get("rows", [])
        for item in items[:20]:
            q = item.get("query", "?")
            linhas.append(f"  - '{q}': {item.get('impressions', 0)} impressões")
        return "\n".join(linhas)

    def _fmt_ga(data):
        linhas = ["Dados GA4 (posts mais lidos, para priorizar):"]
        items = data if isinstance(data, list) else data.get("rows", [])
        for i, item in enumerate(items[:10], 1):
            linhas.append(f"  {i}. {item.get('titulo', item.get('pagePath', '?'))}: "
                          f"{item.get('views', 0)} views")
        return "\n".join(linhas)

    gsc_ctx = _tentar_contexto("gsc_report.py", "GSC", _fmt_gsc)
    ga_ctx = _tentar_contexto("ga_report.py", "GA4", _fmt_ga)

    # 3. Curadoria + validação anti-alucinação
    urls_validas = {a["url"] for a in achados}
    por_url = {a["url"]: a for a in achados}
    pautas = validar_pautas(curar_pautas(achados, gsc_ctx, ga_ctx), urls_validas)

    if not pautas:
        subprocess.run(["python", str(SCRIPT_DIR / "telegram_notify.py"), "send-text",
                        "--message", "⚠️ Pautas da semana: nenhuma pauta com fonte "
                                     "confirmada. Nada foi inventado."],
                       cwd=str(PROJECT_DIR))
        sys.exit(0)

    # 4. Salva estado semanal com fontes completas
    registro = {}
    lista_telegram = []
    for i, p in enumerate(pautas[:10], 1):
        pauta_id = str(i)
        registro[pauta_id] = {
            "titulo": p.get("titulo", ""),
            "keyword": p.get("keyword", ""),
            "categoria": p.get("categoria", ""),
            "wp_category_id": p.get("wp_category_id", 12),
            "justificativa": p.get("justificativa", ""),
            "tipo": p.get("tipo", ""),
            "fontes": [
                {"title": por_url[u].get("title", ""), "url": u,
                 "snippet": por_url[u].get("snippet", "")}
                for u in p.get("fontes", [])
            ],
        }
        primeira_fonte = p["fontes"][0] if p.get("fontes") else ""
        lista_telegram.append({
            "pauta_id": pauta_id, "numero": i,
            "titulo": f"{p.get('titulo', '')} · fonte: {primeira_fonte}",
        })
    PAUTAS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PAUTAS_FILE.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")

    # 5. Telegram
    subprocess.run(["python", str(SCRIPT_DIR / "telegram_notify.py"), "send-pauta-list",
                    "--data", json.dumps(lista_telegram, ensure_ascii=False)],
                   cwd=str(PROJECT_DIR))

    print(f"[pauta_gen] ✅ {len(registro)} pauta(s) com fonte enviadas ao Telegram.", file=sys.stderr)
    print(json.dumps({"pautas": lista_telegram}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
