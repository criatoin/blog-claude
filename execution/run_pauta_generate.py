"""
run_pauta_generate.py — Pipeline autônomo de geração semanal de 10 pautas.

Fluxo:
  1. gsc_report.py (opcional — continua se falhar)
  2. ga_report.py (opcional — continua se falhar)
  3. llm_call() gera 10 sugestões de pauta → JSON array
  4. Para cada pauta: sheets_write.py pauta → coleta IDs retornados
  5. telegram_notify.py send-pauta-list com botões [Produzir 1..10]

Uso:
    python execution/run_pauta_generate.py
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent


def _run_json(args: list[str]) -> dict | list | None:
    """Executa script e parseia stdout como JSON. Retorna None se falhar."""
    result = subprocess.run(
        ["python"] + args,
        capture_output=True, text=True,
        cwd=str(PROJECT_DIR),
    )
    if result.returncode != 0:
        print(f"[run_pauta_generate] Aviso em {Path(args[0]).name}:\n{result.stderr[:500]}", file=sys.stderr)
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _tentar_gsc() -> str:
    """Tenta obter dados do GSC. Retorna string de contexto ou vazio."""
    print("[run_pauta_generate] Tentando GSC...", file=sys.stderr)
    data = _run_json([str(SCRIPT_DIR / "gsc_report.py")])
    if not data:
        print("[run_pauta_generate] GSC indisponível — continuando sem dados GSC.", file=sys.stderr)
        return ""
    # Formata dados GSC para contexto do LLM
    linhas = ["Dados Google Search Console (queries com alto volume, baixo CTR):"]
    items = data if isinstance(data, list) else data.get("rows", [])
    for item in items[:20]:
        query = item.get("query", item.get("keys", ["?"])[0] if isinstance(item.get("keys"), list) else "?")
        impressions = item.get("impressions", 0)
        ctr = item.get("ctr", 0)
        linhas.append(f"  - '{query}': {impressions} impressões, CTR {ctr:.1%}")
    return "\n".join(linhas)


def _tentar_ga() -> str:
    """Tenta obter dados do GA4. Retorna string de contexto ou vazio."""
    print("[run_pauta_generate] Tentando GA4...", file=sys.stderr)
    data = _run_json([str(SCRIPT_DIR / "ga_report.py")])
    if not data:
        print("[run_pauta_generate] GA4 indisponível — continuando sem dados GA4.", file=sys.stderr)
        return ""
    # Formata dados GA para contexto do LLM
    linhas = ["Dados Google Analytics 4 (top posts mais visitados nos últimos 30 dias):"]
    items = data if isinstance(data, list) else data.get("rows", [])
    for i, item in enumerate(items[:10], 1):
        titulo = item.get("titulo", item.get("pagePath", "?"))
        views = item.get("views", item.get("screenPageViews", 0))
        linhas.append(f"  {i}. {titulo}: {views} views")
    return "\n".join(linhas)


def _llm_gerar_pautas(gsc_ctx: str, ga_ctx: str) -> list[dict]:
    """Usa LLM para gerar 10 sugestões de pauta."""
    from llm_call import llm_call_json

    hoje = datetime.now()
    semana = hoje.strftime("Semana de %d/%m/%Y")

    system = """Você é o editor-chefe do +blog, portal de cultura e diversão de Americana, Santa Bárbara d'Oeste (SBO), Nova Odessa e Sumaré (região de Campinas, SP).

Gere 10 sugestões de pauta para a semana atual. Misture tipos:
- Agenda: o que fazer no fim de semana
- Lista: compilação temática
- Matéria explicativa: explica um tema com contexto
- Retrospectiva: balanço de evento passado
- Antevisão: prévia de evento futuro

Regras obrigatórias:
- Só cidades: Americana, SBO, Nova Odessa ou Sumaré
- Só temas: cultura, arte, música, teatro, cinema, dança, cursos gratuitos, diversão
- Título SEO: máx 65 chars, cidade + tema principal
- Priorize pautas com evidência de demanda (GSC/GA)
- Máx 3 pautas do mesmo tipo

Categorias WordPress:
- Música: 23 | Arte: 22 | Audiovisual: 533 | Literatura: 540 | Educação: 384
- Diversão: 11 | Cultura: 13 | Rolês: 19 | Comida: 10 | Eventos: 12

Retorne APENAS um array JSON com 10 objetos (sem markdown):
[{
  "titulo": "...",
  "keyword": "...",
  "categoria": "...",
  "wp_category_id": 19,
  "justificativa": "...",
  "slug_sugerido": "...",
  "tipo": "Agenda|Lista|Explicativa|Retrospectiva|Antevisão"
}]"""

    contexto_dados = ""
    if gsc_ctx:
        contexto_dados += f"\n\n{gsc_ctx}"
    if ga_ctx:
        contexto_dados += f"\n\n{ga_ctx}"
    if not contexto_dados:
        contexto_dados = "\n\nNenhum dado de analytics disponível — use contexto editorial e datas sazonais."

    user = f"""{semana}
{contexto_dados}

Com base nesses dados e no calendário sazonal, gere 10 sugestões de pauta para esta semana."""

    try:
        resultado = llm_call_json(system=system, user=user)
        if isinstance(resultado, list):
            return resultado
        print(f"[run_pauta_generate] LLM retornou formato inesperado: {type(resultado)}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"[run_pauta_generate] Erro ao gerar pautas: {e}", file=sys.stderr)
        return []


def main() -> None:
    print("[run_pauta_generate] Iniciando geração de pautas da semana...", file=sys.stderr)

    # 1. Coleta dados de analytics (opcionais)
    gsc_ctx = _tentar_gsc()
    ga_ctx = _tentar_ga()

    # 2. Gera 10 sugestões de pauta
    print("[run_pauta_generate] Gerando sugestões via LLM...", file=sys.stderr)
    pautas_raw = _llm_gerar_pautas(gsc_ctx, ga_ctx)

    if not pautas_raw:
        print("[run_pauta_generate] Nenhuma pauta gerada. Encerrando.", file=sys.stderr)
        sys.exit(1)

    print(f"[run_pauta_generate] {len(pautas_raw)} pautas geradas.", file=sys.stderr)

    # 3. Salva cada pauta no Sheets e coleta IDs
    pautas_com_id = []
    for i, pauta in enumerate(pautas_raw, 1):
        resultado = _run_json([
            str(SCRIPT_DIR / "sheets_write.py"), "pauta",
            "--data", json.dumps({
                "titulo": pauta.get("titulo", ""),
                "keyword": pauta.get("keyword", ""),
                "categoria": pauta.get("categoria", ""),
                "justificativa": pauta.get("justificativa", ""),
                "status": "Pendente",
                "slug_sugerido": pauta.get("slug_sugerido", ""),
            }, ensure_ascii=False),
        ])

        pauta_id = resultado.get("row_id", str(i)) if resultado else str(i)
        pautas_com_id.append({
            "pauta_id": pauta_id,
            "numero": i,
            "titulo": pauta.get("titulo", ""),
        })
        print(f"[run_pauta_generate]   Pauta #{pauta_id}: {pauta.get('titulo', '')[:50]}", file=sys.stderr)

    # 4. Envia lista ao Telegram com botões [Produzir N]
    subprocess.run(
        [
            "python",
            str(SCRIPT_DIR / "telegram_notify.py"), "send-pauta-list",
            "--data", json.dumps(pautas_com_id, ensure_ascii=False),
        ],
        cwd=str(PROJECT_DIR),
    )

    print(f"\n[run_pauta_generate] ✅ {len(pautas_com_id)} pautas enviadas ao Telegram.", file=sys.stderr)
    print(json.dumps({"pautas": pautas_com_id}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
