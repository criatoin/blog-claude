"""
run_releases.py — Pipeline autônomo de releases: Gmail → WP rascunho → Telegram.

Fluxo:
  1. gmail_fetch.py → lista de emails não lidos
  2. Para cada email: llm_call() avalia relevância
     → não relevante: sheets_write.py log-release (relevante=Não) e pula
  3. llm_call() reescreve post → JSON {titulo, slug, html, wp_category_id, credito_imagem}
  4. Pipeline imagem: image_select.py (anexos) → image_process.py ou image_generate.py
  5. instagram_image.py + legenda via llm_call()
  6. wp_publish.py create --category-id <id>
  7. sheets_write.py log-release + sheets_write.py legenda-ig
  8. telegram_notify.py send-release (SEM --listen — bot daemon cuida dos callbacks)
  9. Imprime resumo

Uso:
    python execution/run_releases.py [--max 10] [--dry-run]
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Guard: roda apenas em dias úteis (seg-sex) entre 8h e 18h
from datetime import datetime
_now = datetime.now()
if _now.weekday() >= 5 or not (8 <= _now.hour < 18):
    print(f"[releases] Fora do horário operacional ({_now.strftime('%a %H:%M')}). Encerrando.")
    sys.exit(0)

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
IG_MODEL = str(PROJECT_DIR / "assets" / "instagram" / "6.jpg")
OUTPUT_DIR = str(PROJECT_DIR / ".tmp")


def _run(args: list[str], capture: bool = True) -> subprocess.CompletedProcess:
    """Executa um script Python e retorna o CompletedProcess."""
    return subprocess.run(
        ["python"] + args,
        capture_output=capture,
        text=True,
        cwd=str(PROJECT_DIR),
    )


def _run_json(args: list[str]) -> dict | list | None:
    """Executa script e parseia stdout como JSON. Retorna None em caso de erro."""
    result = _run(args)
    if result.returncode != 0:
        print(f"[run_releases] Erro em {args[0]}:\n{result.stderr}", file=sys.stderr)
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(f"[run_releases] JSON inválido de {args[0]}: {e}\nSaída: {result.stdout[:500]}", file=sys.stderr)
        return None


def _llm_relevancia(email: dict) -> dict:
    """Avalia se o email é um release relevante para o +blog."""
    from llm_call import llm_call_json

    system = """Você é o editor do +blog, portal de cultura e diversão de Americana, Santa Bárbara d'Oeste (SBO), Nova Odessa e Sumaré.

Critérios de PUBLICAR (TODOS devem ser atendidos):
1. É das cidades: Americana, Santa Bárbara d'Oeste, Nova Odessa ou Sumaré
2. O tema é: cultura, arte, música, teatro, cinema, dança, cursos/aulas gratuitas ou diversão

NÃO PUBLICAR (qualquer um desses → descartar):
- Obras, saúde pública, saneamento, meio ambiente, política, administração municipal
- Esporte profissional/competitivo (exceto evento aberto ao público como diversão)
- Outras cidades sem relação com a região
- Produto comercial puro / propaganda sem conteúdo editorial
- Release duplicado de evento já registrado

Retorne APENAS um objeto JSON:
{"relevante": true/false, "motivo_descarte": "motivo se relevante=false, senão vazio"}"""

    user = f"""Assunto: {email.get('subject', '')}
Remetente: {email.get('sender', '')}
Data: {email.get('date', '')}

Corpo:
{email.get('body_text', '') or email.get('body_html', '')[:3000]}"""

    try:
        return llm_call_json(system=system, user=user)
    except Exception as e:
        print(f"[run_releases] Erro ao avaliar relevância: {e}", file=sys.stderr)
        return {"relevante": False, "motivo_descarte": f"Erro na avaliação: {e}"}


def _llm_reescrever(email: dict) -> dict:
    """Reescreve o email como post do +blog."""
    from llm_call import llm_call_json

    system = """Você é o editor do +blog, portal de cultura e diversão de Americana, SBO, Nova Odessa e Sumaré.

Tom: Natural e direto. Frases curtas. Parágrafos de 2-3 linhas. Sem juridiquês, sem corporativês, sem emoji.
Nunca inventar dados — use [DADO AUSENTE: descrição] se faltar informação.

Estrutura HTML por tipo:
- EVENTO FUTURO: <p>LEAD</p> <p>contexto</p> <p>detalhes</p> <h2>Serviço</h2> <ul>O quê/Quando/Onde/Entrada/Mais info</ul>
- NOTÍCIA/ANÚNCIO: <p>LEAD</p> <p>contexto</p> <p>detalhes</p>
- RETROSPECTIVA: <p>LEAD</p> <p>como foi</p> <p>reações</p>

SEO:
- Título: máx 65 chars, deve ter nome da cidade + tema principal
- Slug: lowercase, hífens, sem acentos, sem stop words

Categorias WordPress:
- Música: 23 | Arte: 22 | Audiovisual: 533 | Literatura: 540 | Educação: 384
- Diversão: 11 | Cultura: 13 | Rolês: 19 | Comida: 10 | Eventos: 12

Retorne APENAS um objeto JSON (sem markdown):
{
  "titulo": "...",
  "slug": "...",
  "wp_category_id": 12,
  "html": "<p>...</p>",
  "credito_imagem": "Foto: Nome via Fonte ou vazio",
  "dados_ausentes": []
}"""

    user = f"""Assunto: {email.get('subject', '')}
Remetente: {email.get('sender', '')}
Data: {email.get('date', '')}

Corpo do release:
{email.get('body_text', '') or email.get('body_html', '')[:5000]}"""

    try:
        return llm_call_json(system=system, user=user)
    except Exception as e:
        raise RuntimeError(f"Erro ao reescrever post: {e}")


def _llm_legenda_ig(titulo: str, html: str) -> str:
    """Gera legenda para Instagram."""
    from llm_call import llm_call

    system = """Você escreve legendas para Instagram do +blog (cultura e diversão na região de Americana/SP).

Regras:
- Máximo 2200 caracteres
- Tom informal, direto, animado
- Primeira linha: gancho forte (sem "Vem aí", sem "Confira")
- 3-5 parágrafos curtos
- Inclua call-to-action no final (ex: "Link na bio para saber mais!")
- Termina com 10-15 hashtags relevantes separadas por espaço
- Sem emoji excessivo (máx 3 por legenda)

Retorne APENAS o texto da legenda, sem explicações."""

    user = f"""Post: {titulo}

Conteúdo resumido:
{html[:1500]}"""

    try:
        return llm_call(system=system, user=user)
    except Exception as e:
        return f"Confira este post incrível no +blog! Link na bio.\n\n#maisblog #americana #culturaameri"


def _pipeline_imagem(email: dict, slug: str) -> str | None:
    """
    Seleciona ou gera imagem de capa. Retorna caminho do cover WebP ou None.
    """
    attachments = email.get("attachments", [])

    if attachments:
        # Tenta selecionar o melhor anexo
        sel_args = [str(SCRIPT_DIR / "image_select.py"), "--images"] + attachments
        sel_result = _run_json(sel_args)
        if sel_result and sel_result.get("path"):
            # Processa para 1920x1080
            proc_result = _run_json([
                str(SCRIPT_DIR / "image_process.py"),
                "--input", sel_result["path"],
                "--slug", slug,
                "--output-dir", OUTPUT_DIR,
            ])
            if proc_result and proc_result.get("path"):
                return proc_result["path"]

    # Gera imagem via Unsplash/Gemini/OpenAI
    print(f"[run_releases] Gerando imagem para slug={slug}...", file=sys.stderr)
    gen_result = _run_json([
        str(SCRIPT_DIR / "image_generate.py"),
        "--query", slug.replace("-", " "),
        "--slug", slug,
        "--output-dir", OUTPUT_DIR,
    ])
    if gen_result and gen_result.get("path"):
        return gen_result["path"]

    return None


def processar_email(email: dict, dry_run: bool = False) -> dict:
    """Processa um email pelo pipeline completo. Retorna dict com resultado."""
    email_id = email.get("id", "?")
    subject = email.get("subject", "")
    sender = email.get("sender", "")
    date = email.get("date", "")

    print(f"\n[run_releases] → Processando: {subject[:60]}", file=sys.stderr)

    # 1. Avalia relevância
    relevancia = _llm_relevancia(email)
    relevante = relevancia.get("relevante", False)
    motivo = relevancia.get("motivo_descarte", "")

    if not relevante:
        print(f"[run_releases]   Não relevante: {motivo}", file=sys.stderr)
        if not dry_run:
            _run_json([
                str(SCRIPT_DIR / "sheets_write.py"), "log-release",
                "--data", json.dumps({
                    "sender": sender,
                    "subject": subject,
                    "date": date,
                    "relevante": False,
                    "status": "Descartado",
                    "motivo_descarte": motivo,
                }, ensure_ascii=False),
            ])
        return {"email_id": email_id, "relevante": False, "motivo": motivo}

    # 2. Reescreve post
    try:
        post = _llm_reescrever(email)
    except RuntimeError as e:
        print(f"[run_releases]   Erro ao reescrever: {e}", file=sys.stderr)
        return {"email_id": email_id, "relevante": True, "error": str(e)}

    titulo = post.get("titulo", subject[:65])
    slug = post.get("slug", "post-sem-slug")
    html = post.get("html", "")
    wp_category_id = post.get("wp_category_id", 12)
    credito_imagem = post.get("credito_imagem", "")

    print(f"[run_releases]   Título: {titulo}", file=sys.stderr)

    if dry_run:
        return {"email_id": email_id, "relevante": True, "titulo": titulo, "slug": slug, "dry_run": True}

    # 3. Pipeline de imagem
    cover_path = _pipeline_imagem(email, slug)
    if not cover_path:
        print(f"[run_releases]   Aviso: sem imagem de capa disponível.", file=sys.stderr)
        cover_path = ""

    # 4. Arte Instagram
    ig_path = ""
    if cover_path and Path(cover_path).exists():
        ig_result = _run_json([
            str(SCRIPT_DIR / "instagram_image.py"),
            "--cover", cover_path,
            "--model", IG_MODEL,
            "--slug", slug,
            "--title", titulo,
            "--output-dir", OUTPUT_DIR,
        ])
        if ig_result:
            ig_path = ig_result.get("path", "")

    # 5. Legenda Instagram
    legenda = _llm_legenda_ig(titulo, html)

    # 6. Cria rascunho no WordPress
    wp_args = [
        str(SCRIPT_DIR / "wp_publish.py"), "create",
        "--title", titulo,
        "--html", html,
        "--category-id", str(wp_category_id),
    ]
    if cover_path:
        wp_args += ["--image-path", cover_path]

    wp_result = _run_json(wp_args)
    if not wp_result:
        print(f"[run_releases]   Erro ao criar rascunho no WP.", file=sys.stderr)
        return {"email_id": email_id, "relevante": True, "titulo": titulo, "error": "wp_publish falhou"}

    post_id = wp_result.get("post_id")
    edit_url = wp_result.get("edit_url", "")

    # 7. Registra no Sheets
    sheets_log = _run_json([
        str(SCRIPT_DIR / "sheets_write.py"), "log-release",
        "--data", json.dumps({
            "sender": sender,
            "subject": subject,
            "date": date,
            "relevante": True,
            "status": "Aguardando aprovação",
            "link_post": edit_url,
        }, ensure_ascii=False),
    ])
    sheets_row_id = sheets_log.get("row_id", "0") if sheets_log else "0"

    if ig_path:
        _run_json([
            str(SCRIPT_DIR / "sheets_write.py"), "legenda-ig",
            "--data", json.dumps({
                "id_post": str(post_id),
                "titulo": titulo,
                "legenda": legenda,
                "hashtags": "",
                "status": "Pronta",
                "path_imagem": ig_path,
            }, ensure_ascii=False),
        ])

    # 8. Notifica Telegram (SEM --listen — bot daemon cuida dos callbacks)
    _run([
        str(SCRIPT_DIR / "telegram_notify.py"), "send-release",
        "--post-id", str(post_id),
        "--title", titulo,
        "--summary", html[:300].replace("<", "").replace(">", "")[:200],
        "--edit-url", edit_url,
        "--cover", cover_path or "",
        "--sheets-row-id", sheets_row_id,
    ])

    print(f"[run_releases]   ✅ Rascunho #{post_id} criado. Card enviado ao Telegram.", file=sys.stderr)

    return {
        "email_id": email_id,
        "relevante": True,
        "titulo": titulo,
        "post_id": post_id,
        "sheets_row_id": sheets_row_id,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline autônomo de releases")
    parser.add_argument("--max", type=int, default=10, help="Máximo de emails a buscar (padrão: 10)")
    parser.add_argument("--dry-run", action="store_true", help="Avalia relevância mas não publica nada")
    args = parser.parse_args()

    print(f"[run_releases] Buscando até {args.max} emails não lidos...", file=sys.stderr)

    emails_result = _run_json([
        str(SCRIPT_DIR / "gmail_fetch.py"),
        "--max", str(args.max),
        "--output-dir", OUTPUT_DIR,
    ])

    if emails_result is None:
        print("[run_releases] Falha ao buscar emails. Encerrando.", file=sys.stderr)
        sys.exit(1)

    emails = emails_result if isinstance(emails_result, list) else []
    print(f"[run_releases] {len(emails)} email(s) encontrado(s).", file=sys.stderr)

    if not emails:
        print("[run_releases] Nenhum email novo. Encerrando.", file=sys.stderr)
        sys.exit(0)

    resultados = []
    for email in emails:
        resultado = processar_email(email, dry_run=args.dry_run)
        resultados.append(resultado)

    # Resumo
    relevantes = [r for r in resultados if r.get("relevante")]
    descartados = [r for r in resultados if not r.get("relevante")]
    erros = [r for r in relevantes if r.get("error")]
    publicados = [r for r in relevantes if r.get("post_id")]

    print(f"\n[run_releases] === Resumo ===", file=sys.stderr)
    print(f"  Total processados: {len(resultados)}", file=sys.stderr)
    print(f"  Relevantes: {len(relevantes)}", file=sys.stderr)
    print(f"  Descartados: {len(descartados)}", file=sys.stderr)
    print(f"  Rascunhos criados: {len(publicados)}", file=sys.stderr)
    if erros:
        print(f"  Erros: {len(erros)}", file=sys.stderr)

    print(json.dumps({"resultados": resultados, "resumo": {
        "total": len(resultados),
        "relevantes": len(relevantes),
        "descartados": len(descartados),
        "rascunhos_criados": len(publicados),
        "erros": len(erros),
    }}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
