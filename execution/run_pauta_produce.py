"""
run_pauta_produce.py — Pipeline autônomo de produção de pauta individual.

Fluxo:
  1. sheets_read.py pauta-id --id <id>
  2. sheets_write.py update-status --status "Produzindo"
  3. search_sources.py --query "<keyword> <cidade>"
     → sufficient=false: atualiza "Sem fontes", notifica Telegram, encerra
  4. llm_call() escreve post completo com fontes
  5. image_generate.py → (já aplica image_process.py internamente)
  6. instagram_image.py + legenda via llm_call()
  7. wp_publish.py create
  8. sheets_write.py legenda-ig + update-status "Produzido"
  9. telegram_notify.py send-release (SEM --listen — bot daemon cuida)

Uso:
    python execution/run_pauta_produce.py --pauta-id <id>
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
IG_MODEL = str(PROJECT_DIR / "assets" / "instagram" / "6.jpg")
OUTPUT_DIR = str(PROJECT_DIR / ".tmp")
VALID_CATEGORY_IDS = {10, 11, 12, 13, 19, 22, 23, 384, 533, 540, 561}
CATEGORY_NAMES = {
    23: "Música", 22: "Arte", 533: "Audiovisual", 540: "Literatura",
    384: "Educação", 11: "Diversão", 561: "Carnaval", 13: "Cultura",
    19: "Rolês", 10: "Comida", 12: "Eventos",
}


def _run(args: list[str], capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python"] + args,
        capture_output=capture, text=True,
        cwd=str(PROJECT_DIR),
    )


def _run_json(args: list[str]) -> dict | list | None:
    result = _run(args)
    if result.returncode != 0:
        print(f"[run_pauta_produce] Erro em {Path(args[0]).name}:\n{result.stderr[:500]}", file=sys.stderr)
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(f"[run_pauta_produce] JSON inválido de {Path(args[0]).name}: {e}", file=sys.stderr)
        return None


def _update_status(pauta_id: str, status: str) -> None:
    _run([
        str(SCRIPT_DIR / "sheets_write.py"), "update-status",
        "--tab", "Pautas",
        "--row-id", pauta_id,
        "--status", status,
    ])


def _gerar_query_imagem(titulo: str, resumo: str = "") -> str:
    """Gera query de busca de imagem em inglês via LLM — foco na atividade/pessoas, nunca na cidade."""
    from llm_call import llm_call
    system = (
        "You generate short image search queries (3-6 words) in English for stock photo sites like Unsplash and Pexels. "
        "Rules:\n"
        "1. Focus on the ACTIVITY or PEOPLE depicted (e.g. 'women fitness class', 'jazz concert crowd', 'cooking class students').\n"
        "2. NEVER include city names, landmarks, parks, buildings, or local infrastructure — "
        "stock photos won't have specific Brazilian city locations.\n"
        "3. Prefer showing REAL PEOPLE doing the activity over empty venues or abstract concepts.\n"
        "4. If it's a fitness/sport event → show people exercising.\n"
        "5. If it's a cultural/arts event → show the art form or audience.\n"
        "6. If it's a food event → show the food or people eating.\n"
        "7. If it's a lecture/talk event → show audience in auditorium or speaker.\n"
        "Output ONLY the query string, nothing else."
    )
    user = f"Article title: {titulo}"
    if resumo:
        user += f"\nSummary: {resumo[:300]}"
    try:
        raw = llm_call(system=system, user=user)
        # Pega apenas a primeira linha não-vazia — LLM às vezes retorna lista
        query = next((l.strip().strip('"').strip("'") for l in raw.splitlines() if l.strip()), "")
        if query:
            print(f"[run_pauta_produce] Query imagem: '{query}'", file=sys.stderr)
            return query
    except Exception as e:
        print(f"[run_pauta_produce] Falha ao gerar query ({e}), usando título.", file=sys.stderr)
    return titulo[:60]


def _llm_escrever_post(pauta: dict, fontes: list[dict]) -> dict:
    """Escreve post completo com base na pauta e nas fontes encontradas."""
    from llm_call import llm_call_json

    fontes_texto = "\n".join([
        f"- [{f.get('title', '')}]({f.get('url', '')}): {f.get('snippet', '')[:300]}"
        for f in fontes
    ])

    urls_fontes = [f.get("url", "") for f in fontes if f.get("url")]
    links_html = " ".join([
        f'<a href="{url}">{fontes[i].get("title", f"Fonte {i+1}")}</a>'
        for i, url in enumerate(urls_fontes[:5])
    ])

    system = """Você é o editor do +blog, portal de cultura e diversão de Americana, SBO, Nova Odessa e Sumaré.

════════════════════════════════
VOZ EDITORIAL
════════════════════════════════
Escreva como um amigo da cidade contando uma boa novidade — informal, direto, entusiasmado sem exagero.
Abra com um hook forte que prenda a atenção logo na primeira linha.
Frases curtas. Parágrafos de 3–5 linhas. Nunca parágrafo de linha única.
Palavras proibidas: "robusto", "sinergia", "ecossistema", "haja vista", "no que tange", "destarte".
Sem emoji. Nunca inventar dados — use [DADO AUSENTE: descrição] se faltar informação.
Cite as fontes no final com <p><em>Fontes: <a href="url">título</a></em></p>

════════════════════════════════
QUALIDADE DE CONTEÚDO — REGRA ABSOLUTA
════════════════════════════════
Use CADA dado presente nas fontes: nomes, datas, horários, locais, valores, citações, programação.
MÍNIMO OBRIGATÓRIO: 500 palavras de conteúdo (excluindo o bloco Serviço).
Escreva 5–6 parágrafos ricos. Jamais 2 parágrafos rasos.
O leitor deve saber exatamente o quê, quando, onde, quanto custa e como participar.

════════════════════════════════
HTML PURO — PROIBIDO USAR MARKDOWN
════════════════════════════════
O campo "html" deve conter APENAS tags HTML. NUNCA use Markdown.

PROIBIDO:  ** texto **  /  ## Título  /  * item  /  # Título
OBRIGATÓRIO:
  Negrito   →  <strong>texto</strong>
  Subtítulo →  <h2>Texto</h2>
  Parágrafo →  <p>texto</p>
  Lista     →  <ul><li>item</li></ul>

════════════════════════════════
ESTRUTURA POR TIPO
════════════════════════════════
EVENTO FUTURO:
<p>[Hook + o quê/quando/onde/quem]</p>
<p>[Contexto e por que vale a pena]</p>
<p>[Programação completa com <strong> nos nomes]</p>
<h2>Serviço</h2>
<ul><li><strong>O quê:</strong> ...</li><li><strong>Quando:</strong> ...</li>
<li><strong>Onde:</strong> ...</li><li><strong>Entrada:</strong> ...</li>
<li><strong>Mais informações:</strong> ...</li></ul>

LISTA (o que fazer, top N lugares):
<p>[Intro engajante]</p>
<h2>[Nome do item 1]</h2><p>[Descrição com endereço, horários, destaques]</p>
<h2>[Nome do item 2]</h2><p>[idem]</p>
... (repetir para cada item)

AGENDA (compilação de eventos):
<p>[Intro: contexto da semana/período]</p>
<h2>[Nome do Evento]</h2><p>[Descrição]</p>
<ul><li><strong>Quando:</strong> ...</li><li><strong>Onde:</strong> ...</li><li><strong>Entrada:</strong> ...</li></ul>
... (repetir para cada evento)

NOTÍCIA/ANÚNCIO:
<p>[Hook com o fato principal]</p>
<p>[Contexto: por que importa para o morador?]</p>
<p>[Detalhes completos com números, prazos, declarações]</p>
<p>[Próximos passos se houver]</p>

════════════════════════════════
SEO
════════════════════════════════
Título: máx 65 chars, cidade + tema principal.
Slug: lowercase, hífens, sem acentos, sem stop words.

════════════════════════════════
CATEGORIAS WORDPRESS
════════════════════════════════
Música: 23 | Arte: 22 | Audiovisual: 533 | Literatura: 540 | Educação: 384
Diversão: 11 | Cultura: 13 | Rolês: 19 | Comida: 10 | Eventos: 12

TAGS: 5–8 tags lowercase. Ex: ["americana", "cultura", "show gratuito", "teatro"]

Retorne APENAS um objeto JSON válido (sem markdown, sem blocos ```json):
{
  "titulo": "...",
  "slug": "...",
  "wp_category_id": 19,
  "html": "<p>...</p>",
  "tags": ["tag1", "tag2"],
  "dados_ausentes": []
}"""

    user = f"""Pauta para produzir:
- Título sugerido: {pauta.get('titulo', '')}
- Keyword: {pauta.get('keyword', '')}
- Categoria: {pauta.get('categoria', '')}
- Justificativa: {pauta.get('justificativa', '')}
- Tipo: {pauta.get('tipo', 'Matéria')}

Fontes encontradas:
{fontes_texto}

Links para citar no HTML: {links_html}

Escreva o post completo com base nessas fontes."""

    try:
        return llm_call_json(system=system, user=user)
    except Exception as e:
        raise RuntimeError(f"Erro ao escrever post: {e}")


def _llm_legenda_ig(titulo: str, html: str) -> str:
    """Gera legenda para Instagram."""
    from llm_call import llm_call

    system = """Você é um especialista em social media com 10 anos de experiência em contas de cultura e entretenimento local.
Cria legendas para o @maisblogoficial — portal de cultura e diversão da região de Americana/SP.

## Estrutura obrigatória (nesta ordem, sem variações)

1. **GANCHO** — 1 linha única, antes do "ver mais"
   - Prenda o scroll com um dado concreto, data, valor, ou fato específico do post.
   - PROIBIDO: "Vem aí", "Confira", "Sabia que", "Que tal", "Incrível", "Não perca".
   - BOM: "Entrada gratuita, sábado, 15h." / "Festival de jazz no Mercadão neste sábado."

2. **CORPO** — 2 parágrafos curtos (máx 2 linhas cada), separados por linha em branco
   - Detalhes concretos: onde, quando, o quê, pra quem, quanto custa.
   - Tom de amigo dando uma dica — nunca assessoria de imprensa.

3. **CTA obrigatório** — 1 linha exata, SEMPRE convidando a ler a matéria completa no site
   - Use uma dessas frases (escolha a mais natural): "Matéria completa no +blog — link na bio 🔗" / "Todos os detalhes no +blog — link na bio." / "Leia a matéria completa: link na bio."
   - NUNCA use "Salva esse post" como único CTA — sempre direcione ao site.

4. **HASHTAGS** — linha separada, EXATAMENTE 5, nem mais nem menos
   - Formato: 2 do tema + 2 da cidade/região + 1 da marca (#maisblog obrigatória)
   - Cidades: #americana #santabarbaradoeste #novaodessa #sumare #interiordeSP
   - REGRA DURA: conte as hashtags antes de finalizar. Se tiver mais de 5, remova as excedentes.

## Restrições de tamanho
- Gancho: máx 100 caracteres
- Total da legenda (incluindo hashtags): máx 800 caracteres
- Se ultrapassar 800 caracteres, corte o corpo — nunca corte o CTA nem as hashtags.

## Tom e estilo
- Especialista em redes sociais que conhece a região — voz próxima, direta, sem exageros.
- Emojis: máx 2 por legenda, apenas funcionais (📌 🔗 🎭 🎶 — não decorativos).
- Zero adjetivos vazios: "incrível", "maravilhoso", "imperdível", "fantástico", "especial".
- Zero frases de assessoria: "a prefeitura informa", "o evento contará com", "não perca a oportunidade".

Retorne APENAS o texto final da legenda. Sem prefixos, sem explicações, sem markdown."""

    user = f"""Post: {titulo}

Conteúdo:
{html[:2000]}"""

    try:
        return llm_call(system=system, user=user)
    except Exception:
        return "Confira este post incrível no +blog! Link na bio.\n\n#maisblog #americana #cultura"


def main() -> None:
    parser = argparse.ArgumentParser(description="Produz uma pauta individual")
    parser.add_argument("--pauta-id", required=True, help="ID da pauta na planilha Pautas")
    args = parser.parse_args()

    pauta_id = args.pauta_id
    print(f"[run_pauta_produce] Produzindo pauta #{pauta_id}...", file=sys.stderr)

    # 1. Lê dados da pauta
    pauta = _run_json([
        str(SCRIPT_DIR / "sheets_read.py"), "pauta-id",
        "--id", pauta_id,
    ])
    if not pauta:
        print(f"[run_pauta_produce] Pauta #{pauta_id} não encontrada.", file=sys.stderr)
        sys.exit(1)

    keyword = pauta.get("keyword", "")
    titulo_sugerido = pauta.get("titulo", "")
    cidade = "Americana"  # default; keyword geralmente já contém a cidade

    print(f"[run_pauta_produce] Pauta: {titulo_sugerido}", file=sys.stderr)

    # 2. Atualiza status para "Produzindo"
    _update_status(pauta_id, "Produzindo")

    # 3. Busca fontes
    query = f"{keyword} {cidade}" if cidade.lower() not in keyword.lower() else keyword
    print(f"[run_pauta_produce] Buscando fontes: '{query}'...", file=sys.stderr)

    fontes_result = _run_json([
        str(SCRIPT_DIR / "search_sources.py"),
        "--query", query,
    ])

    if not fontes_result or not fontes_result.get("sufficient", False):
        motivo = "Fontes insuficientes para produzir com qualidade."
        print(f"[run_pauta_produce] {motivo}", file=sys.stderr)
        _update_status(pauta_id, "Sem fontes")
        subprocess.run([
            "python",
            str(SCRIPT_DIR / "telegram_notify.py"), "send-text",
            "--message", f"⚠️ Pauta #{pauta_id} — {titulo_sugerido[:50]}\n{motivo}",
        ], cwd=str(PROJECT_DIR))
        sys.exit(0)

    fontes = fontes_result.get("sources", [])
    print(f"[run_pauta_produce] {len(fontes)} fonte(s) encontrada(s).", file=sys.stderr)

    # 4. Escreve post com LLM
    try:
        post = _llm_escrever_post(pauta, fontes)
    except RuntimeError as e:
        print(f"[run_pauta_produce] {e}", file=sys.stderr)
        _update_status(pauta_id, "Erro na produção")
        sys.exit(1)

    titulo = post.get("titulo", titulo_sugerido[:65])
    slug = post.get("slug", titulo_sugerido.lower().replace(" ", "-")[:50])
    html = post.get("html", "")
    wp_category_id = post.get("wp_category_id", pauta.get("wp_category_id", 12))
    if wp_category_id not in VALID_CATEGORY_IDS:
        print(f"[run_pauta_produce] Categoria inválida ({wp_category_id}), usando Eventos (12).", file=sys.stderr)
        wp_category_id = 12
    tags = post.get("tags", [])

    print(f"[run_pauta_produce] Título: {titulo}", file=sys.stderr)

    # 5. Gera imagem de capa
    img_query = _gerar_query_imagem(titulo)
    print(f"[run_pauta_produce] Gerando imagem | query='{img_query}'...", file=sys.stderr)
    gen_result = _run_json([
        str(SCRIPT_DIR / "image_generate.py"),
        "--query", img_query,
        "--slug", slug,
        "--titulo", titulo,
        "--output-dir", OUTPUT_DIR,
    ])
    cover_path = gen_result.get("path", "") if gen_result else ""
    foto_credit = (gen_result.get("credit", "") if gen_result else "") or "Divulgação"

    # 6. Arte Instagram
    ig_path = ""
    ig_url = ""
    if cover_path and Path(cover_path).exists():
        category_name = CATEGORY_NAMES.get(wp_category_id, "Eventos")
        ig_result = _run_json([
            str(SCRIPT_DIR / "instagram_image.py"),
            "--cover", cover_path,
            "--slug", slug,
            "--title", titulo,
            "--category", category_name,
            "--output-dir", OUTPUT_DIR,
        ])
        if ig_result:
            ig_path = ig_result.get("path", "")

    # Upload da arte IG para WP Media Library
    if ig_path and Path(ig_path).exists():
        upload_result = _run_json([
            str(SCRIPT_DIR / "wp_publish.py"), "upload-image",
            "--image-path", ig_path,
            "--title", f"{titulo} — Instagram",
        ])
        if upload_result:
            ig_url = upload_result.get("url", "")

    # 7. Legenda Instagram
    legenda = _llm_legenda_ig(titulo, html)

    # 8. Cria rascunho no WordPress
    creditos_html = (
        f'<p><small><em>Texto: Equipe do +blog. '
        f'Fotos: {foto_credit}</em></small></p>'
    )
    html_com_creditos = html + "\n" + creditos_html

    wp_args = [
        str(SCRIPT_DIR / "wp_publish.py"), "create",
        "--title", titulo,
        "--html", html_com_creditos,
        "--category-id", str(wp_category_id),
    ]
    if cover_path:
        wp_args += ["--image-path", cover_path]
    if tags:
        wp_args += ["--tags", ",".join(tags)]

    wp_result = _run_json(wp_args)
    if not wp_result:
        print("[run_pauta_produce] Falha ao criar rascunho no WP.", file=sys.stderr)
        _update_status(pauta_id, "Erro na produção")
        sys.exit(1)

    post_id = wp_result.get("post_id")
    edit_url = wp_result.get("edit_url", "")

    # 9. Salva legenda IG no Sheets
    if ig_url:
        _run_json([
            str(SCRIPT_DIR / "sheets_write.py"), "legenda-ig",
            "--data", json.dumps({
                "id_post": str(post_id),
                "titulo": titulo,
                "legenda": legenda,
                "hashtags": "",
                "status": "Pronta",
                "path_imagem": ig_url,
            }, ensure_ascii=False),
        ])

    # Atualiza status da pauta
    _update_status(pauta_id, "Produzido")

    # Atualiza link_post na pauta (coluna H = index 7)
    # Nota: update-status só atualiza coluna "status" — link_post seria outra chamada
    # Por ora, registramos via update-status com valor composto não é possível.
    # Deixamos o link editável no rascunho do WP.

    # 10. Notifica Telegram (SEM --listen — bot daemon cuida)
    subprocess.run([
        "python",
        str(SCRIPT_DIR / "telegram_notify.py"), "send-release",
        "--post-id", str(post_id),
        "--title", titulo,
        "--summary", html[:300].replace("<", "").replace(">", "")[:200],
        "--edit-url", edit_url,
        "--cover", cover_path or "",
        "--sheets-row-id", pauta_id,
    ], cwd=str(PROJECT_DIR))

    print(f"[run_pauta_produce] ✅ Rascunho #{post_id} criado. Card enviado ao Telegram.", file=sys.stderr)
    print(json.dumps({
        "pauta_id": pauta_id,
        "post_id": post_id,
        "titulo": titulo,
        "edit_url": edit_url,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
