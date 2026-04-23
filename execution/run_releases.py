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

# Guard: roda apenas em dias úteis (seg-sex) entre 8h e 18h (horário de Brasília explícito)
from datetime import datetime
from zoneinfo import ZoneInfo
_now = datetime.now(ZoneInfo("America/Sao_Paulo"))
if _now.weekday() >= 5 or not (8 <= _now.hour < 18):
    print(f"[releases] Fora do horário operacional ({_now.strftime('%a %H:%M')}). Encerrando.")
    sys.exit(0)

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
IG_MODEL = str(PROJECT_DIR / "assets" / "instagram" / "6.jpg")
OUTPUT_DIR = str(PROJECT_DIR / ".tmp")
PROCESSED_FILE = PROJECT_DIR / ".tmp" / "processed_emails.json"
VALID_CATEGORY_IDS = {10, 11, 12, 13, 19, 22, 23, 384, 533, 540, 561}
CATEGORY_NAMES = {
    23: "Música", 22: "Arte", 533: "Audiovisual", 540: "Literatura",
    384: "Educação", 11: "Diversão", 561: "Carnaval", 13: "Cultura",
    19: "Rolês", 10: "Comida", 12: "Eventos",
}


def _load_processed() -> set:
    if PROCESSED_FILE.exists():
        return set(json.loads(PROCESSED_FILE.read_text(encoding="utf-8")))
    return set()


def _load_processed_from_sheets() -> set:
    """
    Lê Log Releases do Sheets e retorna set de (assunto_lower, sender_lower) já processados.
    Serve como dedup persistente: sobrevive ao restart do container mesmo sem processed_emails.json.
    """
    try:
        result = _run_json([str(SCRIPT_DIR / "sheets_read.py"), "log"])
        if not result:
            return set()
        return {
            (r.get("assunto", "").strip().lower(), r.get("origem_email", "").strip().lower())
            for r in result
            if r.get("status") not in ("Descartado",)
        }
    except Exception as e:
        print(f"[run_releases] Aviso: falha ao carregar dedup do Sheets: {e}", file=sys.stderr)
        return set()


def _mark_processed(email_id: str) -> None:
    processed = _load_processed()
    processed.add(email_id)
    if len(processed) > 500:
        processed = set(list(processed)[-500:])
    PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROCESSED_FILE.write_text(json.dumps(list(processed), ensure_ascii=False), encoding="utf-8")


def _run(args: list[str], capture: bool = True) -> subprocess.CompletedProcess:
    """Executa um script Python e retorna o CompletedProcess."""
    return subprocess.run(
        ["python"] + args,
        capture_output=capture,
        text=True,
        encoding="utf-8",
        errors="replace",
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

    system = """Você é o editor do +blog, portal de cultura e diversão de Americana, Santa Bárbara d'Oeste (SBO), Nova Odessa e Sumaré.

════════════════════════════════
VOZ EDITORIAL
════════════════════════════════
Escreva como um amigo da cidade contando uma boa novidade — informal, direto, entusiasmado sem exagero.
Abra com um hook forte que prenda a atenção logo na primeira linha (ex: "A galera que curte teatro em SBO tem novidade boa essa semana.").
Frases curtas. Parágrafos de 3–5 linhas. Nunca parágrafo de linha única.
Palavras proibidas: "robusto", "sinergia", "ecossistema", "haja vista", "no que tange", "destarte", "ademais".
Sem emoji. Sem jargão corporativo.
Nunca inventar dados — use [DADO AUSENTE: descrição] se faltar informação.

════════════════════════════════
QUALIDADE DE CONTEÚDO — REGRA ABSOLUTA
════════════════════════════════
PROIBIDO resumir o release. Use CADA dado presente no email original:
- Todo artista, atração, palestrante, convidado → cite pelo nome completo
- Toda data, horário, local, endereço → transcreva completo
- Todo valor, forma de inscrição, link, telefone → inclua
- Toda citação de organizador, secretário, autoridade → use entre aspas com atribuição
- Toda programação, cronograma ou lista de atividades → reproduza integralmente

MÍNIMO OBRIGATÓRIO: 500 palavras de conteúdo (excluindo o bloco Serviço).
Escreva 5–6 parágrafos ricos e densos. Jamais 2 parágrafos rasos.
O leitor deve saber exatamente o quê, quando, onde, quanto custa e como participar.
Se o release mencionar múltiplos eventos ou datas, detalhe CADA UM.

════════════════════════════════
HTML PURO — PROIBIDO USAR MARKDOWN
════════════════════════════════
O campo "html" deve conter APENAS tags HTML. NUNCA use Markdown.

PROIBIDO (causa quebra visual no site):
  ** texto **   →  use  <strong>texto</strong>
  * texto *     →  use  <em>texto</em>
  ## Título     →  use  <h2>Título</h2>
  # Título      →  use  <h2>Título</h2>
  - item        →  use  <ul><li>item</li></ul>

OBRIGATÓRIO:
  Negrito       →  <strong>texto</strong>
  Itálico       →  <em>texto</em>
  Subtítulo     →  <h2>Texto</h2>
  Parágrafo     →  <p>texto</p>
  Lista         →  <ul><li>item</li></ul>

════════════════════════════════
ESTRUTURA POR TIPO
════════════════════════════════

[EVENTO FUTURO] — show, feira, festival, palestra, curso, exposição:
<p>[Hook forte: 1–2 frases que antecipam o evento com entusiasmo real. Diga o quê, quando e onde.]</p>
<p>[Contexto: por que vale a pena ir? O que o leitor vai encontrar lá? Cite o organizador se o release mencionar, com aspas e atribuição.]</p>
<p>[Programação completa: liste CADA atração, artista, atividade citada no release. Use <strong> nos nomes de artistas e eventos.]</p>
<p>[Detalhes práticos: inscrição, o que levar, faixa etária, acessibilidade, estacionamento — tudo que estiver no release.]</p>
<h2>Serviço</h2>
<ul>
  <li><strong>O quê:</strong> [nome completo do evento]</li>
  <li><strong>Quando:</strong> [data e horário completos]</li>
  <li><strong>Onde:</strong> [endereço completo com bairro e cidade]</li>
  <li><strong>Entrada:</strong> [gratuita / valor / como obter ingresso / link]</li>
  <li><strong>Mais informações:</strong> [telefone / site / redes sociais / WhatsApp]</li>
</ul>

[NOTÍCIA/ANÚNCIO] — novidade institucional, resultado, conquista:
<p>[Hook: o fato principal em 1–2 frases. Quem fez o quê, de forma direta e engajante.]</p>
<p>[Contexto: por que isso importa para o morador? Qual problema resolve ou que avanço representa?]</p>
<p>[Detalhes: números, prazos, etapas, declarações. Cite quem disse o quê, com atribuição. Não resuma — use os dados do release completos.]</p>
<p>[Próximos passos ou desdobramentos, se houver no release.]</p>

[RETROSPECTIVA] — balanço, resultado, evento já realizado:
<p>[Hook: o resultado principal de forma viva — dê a dimensão do que aconteceu.]</p>
<p>[Como foi: dados de público, números, destaques da programação, momentos marcantes.]</p>
<p>[Reações: citações de organizadores, participantes ou autoridades presentes, com atribuição.]</p>
<p>[Próxima edição ou desdobramentos, se houver no release.]</p>

════════════════════════════════
SEO
════════════════════════════════
Título: máx 65 chars. Fórmula: [tema principal] + [cidade] + [data/contexto se couber].
Exemplos: "Festival de Jazz chega a Americana em abril", "Curso gratuito de teatro abre inscrições em SBO"
Slug: lowercase, hífens, sem acentos, sem stop words, sem underscore.
Keyword principal no primeiro parágrafo.

════════════════════════════════
CATEGORIAS WORDPRESS (use o ID exato)
════════════════════════════════
Show, concerto, festival de música → Música: 23
Teatro, dança, circo, performance → Arte: 22
Cinema, série, documentário → Audiovisual: 533
Livro, leitura, autor, literatura → Literatura: 540
Curso gratuito, oficina, palestra, workshop → Educação: 384
Festa, carnaval, bloco → Diversão: 11 (Carnaval: 561 se for carnaval)
Exposição, museu, galeria → Cultura: 13
O que fazer / evento misto → Rolês: 19
Gastronomia, restaurante, feira de comida → Comida: 10
Evento geral sem categoria específica → Eventos: 12
Prefira sempre a mais específica. Ex: "Círculo do Livro" → Literatura (540), nunca Eventos (12).

════════════════════════════════
TAGS
════════════════════════════════
Gere 5–8 tags em lowercase. Inclua: nome da cidade, tema, nome do evento ou local.
Exemplos: ["americana", "musica ao vivo", "show gratuito", "teatro municipal", "cultura"]

Retorne APENAS um objeto JSON válido (sem markdown, sem blocos ```json):
{
  "titulo": "...",
  "slug": "...",
  "wp_category_id": 12,
  "html": "<p>...</p>",
  "tags": ["tag1", "tag2", "tag3"],
  "credito_imagem": "Foto: Nome via Fonte ou vazio",
  "credito_texto": "Nome do autor ou assessoria que assina o release (ex: 'Secom / Prefeitura de Americana', 'Assessoria SESC', 'Daniela Alves (MTb 23.611)'). Se não identificado, use o nome da organização remetente.",
  "dados_ausentes": []
}"""

    user = f"""Assunto: {email.get('subject', '')}
Remetente: {email.get('sender', '')}
Data: {email.get('date', '')}

Corpo do release:
{email.get('body_text', '') or email.get('body_html', '')[:8000]}"""

    try:
        return llm_call_json(system=system, user=user)
    except Exception as e:
        raise RuntimeError(f"Erro ao reescrever post: {e}")


def _llm_legenda_ig(titulo: str, html: str) -> str:
    """Gera legenda para Instagram."""
    from llm_call import llm_call

    system = """Você é um especialista em social media com 10 anos de experiência em contas de cultura e entretenimento local.
Cria legendas para o @maisblogoficial — portal de cultura e diversão da região de Americana/SP.

## Estrutura obrigatória (nesta ordem, sem variações)

1. **GANCHO** — 1 linha única, antes do "ver mais"
   - Prenda o scroll com um dado concreto, data, valor, ou fato específico do post.
   - PROIBIDO: "Vem aí", "Confira", "Sabia que", "Que tal", "Incrível", "Não perca".
   - BOM: "Entrada gratuita, sábado, 15h." / "R$ 225 mil disponíveis para festivais culturais em Americana."

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
    except Exception as e:
        return f"Confira este post incrível no +blog! Link na bio.\n\n#maisblog #americana #culturaameri"


def _imagem_relevante(image_path: str, titulo: str) -> bool:
    """
    Usa Gemini Vision para verificar se a imagem é relevante ao título do post.
    Retorna True se relevante, False se não (→ cai para Unsplash/Gemini).
    """
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return True  # sem chave, aceita imagem sem verificar

    try:
        from google import genai
        from google.genai import types
        from PIL import Image as PILImage

        client = genai.Client(api_key=api_key)
        img = PILImage.open(image_path).convert("RGB")

        import io
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        img_bytes = buf.getvalue()

        prompt = (
            f"This image came attached to a press release from a Brazilian city hall. "
            f"Analyze it in two strict sequential steps. Answer ONLY 'yes' or 'no'.\n\n"
            f"STEP 1 — IMAGE TYPE:\n"
            f"Is this image PRIMARILY a graphic design piece (logo, flyer, poster, infographic, "
            f"corporate seal, illustration) where TEXT or BRAND ELEMENTS dominate the visual?\n"
            f"→ If the image is a REAL PHOTOGRAPH of people, places, or events — even if it has "
            f"incidental text on signs or banners — answer 'yes' and continue.\n"
            f"→ Only answer 'no' (reject) if the image is clearly a graphic design, not a photo.\n\n"
            f"STEP 2 — CULTURAL CONTEXT (only if Step 1 passed):\n"
            f"This image will appear on a Brazilian news blog. "
            f"Does the image show people in cultural dress CLEARLY incompatible with Brazil "
            f"(hijab, sari, East Asian traditional costume)? "
            f"Casual clothing, school uniforms, stage costumes, and local event attire are all fine.\n"
            f"→ Only answer 'no' (reject) if incompatible cultural markers are UNMISTAKABLY visible.\n"
            f"→ Otherwise answer 'yes'.\n\n"
            f"Post title for context (do NOT use this to reject the image — it's just context): '{titulo}'\n\n"
            f"IMPORTANT: This is a real press release photo. Err on the side of accepting. "
            f"Only reject if the image is clearly a graphic/logo (Step 1) or clearly foreign cultural dress (Step 2)."
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                prompt,
                types.Part(inline_data=types.Blob(mime_type="image/jpeg", data=img_bytes)),
            ],
        )
        # Extrai a última palavra "yes" ou "no" da resposta — Gemini às vezes
        # formata os steps por extenso antes de dar a resposta final.
        import re as _re
        words = _re.findall(r"\b(yes|no)\b", response.text.strip().lower())
        relevant = words[-1] == "yes" if words else False
        if not relevant:
            print(f"[run_releases] Imagem rejeitada (logo/não-foto/irrelevante) para '{titulo[:50]}' — usando Unsplash/Gemini.", file=sys.stderr)
        else:
            print(f"[run_releases] Imagem aprovada pela vision para '{titulo[:50]}'.", file=sys.stderr)
        return relevant

    except Exception as e:
        err_str = str(e)
        is_server_overload = (
            "'code': 503" in err_str
            or '"code": 503' in err_str
            or "503 UNAVAILABLE" in err_str
        )
        if is_server_overload:
            print(f"[run_releases] Vision API indisponível (503), aceitando foto do email sem validar.", file=sys.stderr)
            return True
        print(f"[run_releases] Aviso: verificação de relevância falhou ({e}), rejeitando imagem por precaução.", file=sys.stderr)
        return False


def _gerar_query_imagem(titulo: str, resumo: str = "") -> str:
    """
    Usa LLM para gerar uma query de busca de imagem em inglês.
    Foca na atividade/pessoas — nunca em landmarks ou infraestrutura da cidade.
    """
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
        from llm_call import llm_call
        raw = llm_call(system=system, user=user)
        # Pega apenas a primeira linha não-vazia — LLM às vezes retorna lista
        query = next((l.strip().strip('"').strip("'") for l in raw.splitlines() if l.strip()), "")
        if query:
            print(f"[run_releases] Query imagem gerada: '{query}'", file=sys.stderr)
            return query
    except Exception as e:
        print(f"[run_releases] Falha ao gerar query de imagem ({e}), usando slug.", file=sys.stderr)
    return titulo[:60]


def _pipeline_imagem(email: dict, slug: str, titulo: str = "") -> tuple[str, str]:
    """
    Seleciona ou gera imagem de capa.

    Prioridade estrita:
      1) Fotos do próprio email (anexos diretos ou álbuns Flickr baixados pelo gmail_fetch)
         — tenta TODAS as fotos em ordem de score, aceita a primeira que _imagem_relevante aprovar.
         Fotos reais do evento/local sempre preferidas sobre qualquer imagem gerada.
      2) Banco de fotos gratuito (Unsplash → Pexels) — só se não houver NENHUMA foto do email.
      3) Geração por IA (Gemini → OpenAI) — último recurso absoluto.

    Retorna (cover_path, foto_credit).
    """
    attachments = email.get("attachments", [])

    if attachments:
        # Pontua e ordena todas as fotos do email por score (melhor primeiro)
        import subprocess as _sp
        scored = []
        for att in attachments:
            r = _run_json([str(SCRIPT_DIR / "image_select.py"), "--images", att])
            if r and r.get("score", -1) >= 0:
                scored.append(r)
        scored.sort(key=lambda x: x.get("score", 0), reverse=True)

        print(f"[run_releases] {len(scored)} foto(s) do email para avaliar.", file=sys.stderr)

        for candidate in scored:
            cpath = candidate.get("path")
            if not cpath:
                continue
            if titulo and not _imagem_relevante(cpath, titulo):
                print(f"[run_releases] Foto do email rejeitada (vision): {Path(cpath).name}", file=sys.stderr)
                continue
            # Foto aprovada — processa e retorna
            proc_result = _run_json([
                str(SCRIPT_DIR / "image_process.py"),
                "--input", cpath,
                "--slug", slug,
                "--output-dir", OUTPUT_DIR,
            ])
            if proc_result and proc_result.get("path"):
                print(f"[run_releases] Usando foto do email: {Path(cpath).name}", file=sys.stderr)
                return proc_result["path"], ""

        print(f"[run_releases] Nenhuma foto do email aprovada. Tentando bancos de imagem.", file=sys.stderr)

    # Só chega aqui se não havia fotos no email ou todas foram rejeitadas pela vision.
    # Tenta Unsplash/Pexels antes de gerar por IA.
    img_query = _gerar_query_imagem(titulo)
    print(f"[run_releases] Buscando imagem em bancos gratuitos | query='{img_query}'...", file=sys.stderr)
    gen_result = _run_json([
        str(SCRIPT_DIR / "image_generate.py"),
        "--query", img_query,
        "--slug", slug,
        "--titulo", titulo,
        "--output-dir", OUTPUT_DIR,
    ])
    if gen_result and gen_result.get("path"):
        source = gen_result.get("source", "?")
        print(f"[run_releases] Imagem obtida via {source}.", file=sys.stderr)
        return gen_result["path"], gen_result.get("credit", "")

    return "", ""


def processar_email(email: dict, dry_run: bool = False, processed_subjects: set | None = None) -> dict:
    """Processa um email pelo pipeline completo. Retorna dict com resultado."""
    email_id = email.get("id", "?")
    subject = email.get("subject", "")
    sender = email.get("sender", "")
    date = email.get("date", "")

    # Deduplicação 1: arquivo local (rápido, perdido no restart)
    if not dry_run and email_id in _load_processed():
        print(f"\n[run_releases] → Já processado (arquivo), pulando: {subject[:60]}", file=sys.stderr)
        return {"email_id": email_id, "relevante": False, "motivo": "Já processado anteriormente"}

    # Deduplicação 2: Sheets (persistente entre restarts do container)
    if not dry_run and processed_subjects is not None:
        key = (subject.strip().lower(), sender.strip().lower())
        if key in processed_subjects:
            print(f"\n[run_releases] → Já na planilha, pulando: {subject[:60]}", file=sys.stderr)
            return {"email_id": email_id, "relevante": False, "motivo": "Já registrado na planilha"}

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
    if wp_category_id not in VALID_CATEGORY_IDS:
        print(f"[run_releases]   Categoria inválida ({wp_category_id}), usando Eventos (12).", file=sys.stderr)
        wp_category_id = 12
    tags = post.get("tags", [])
    credito_imagem = post.get("credito_imagem", "")
    credito_texto = post.get("credito_texto", "") or sender.split("<")[0].strip() or "Assessoria"

    print(f"[run_releases]   Título: {titulo}", file=sys.stderr)

    if dry_run:
        return {"email_id": email_id, "relevante": True, "titulo": titulo, "slug": slug, "dry_run": True}

    # 3. Pipeline de imagem
    cover_path, foto_credit_gerada = _pipeline_imagem(email, slug, titulo)
    if not cover_path:
        print(f"[run_releases]   Aviso: sem imagem de capa disponível.", file=sys.stderr)
        cover_path = ""
    # Crédito final: prioriza o do release; fallback para crédito da imagem gerada
    foto_credit = credito_imagem or foto_credit_gerada or "Divulgação"

    # 4. Arte Instagram
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

    # 5. Legenda Instagram
    legenda = _llm_legenda_ig(titulo, html)

    # 6. Cria rascunho no WordPress
    # Adiciona bloco de créditos ao final do HTML
    creditos_html = (
        f'<p><small><em>Texto: {credito_texto}, reescrito pela equipe do +blog. '
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
        print(f"[run_releases]   Erro ao criar rascunho no WP.", file=sys.stderr)
        return {"email_id": email_id, "relevante": True, "titulo": titulo, "error": "wp_publish falhou"}

    # Marca email como processado para evitar duplicação em runs futuros
    _mark_processed(email_id)

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

    # 8. Notifica Telegram (SEM --listen — bot daemon cuida dos callbacks)
    notify_args = [
        str(SCRIPT_DIR / "telegram_notify.py"), "send-release",
        "--post-id", str(post_id),
        "--title", titulo,
        "--summary", html[:300].replace("<", "").replace(">", "")[:200],
        "--edit-url", edit_url,
        "--cover", cover_path or "",
        "--sheets-row-id", sheets_row_id,
    ]
    if ig_path:
        notify_args += ["--ig-image", ig_path, "--ig-caption", legenda]
    notify_result = _run(notify_args)
    if notify_result.returncode != 0:
        print(f"[run_releases]   Aviso: telegram_notify falhou (código {notify_result.returncode}):\n"
              f"{notify_result.stderr[:500]}", file=sys.stderr)

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

    # Carrega dedup persistente do Sheets uma única vez (evita chamada por email)
    processed_subjects = _load_processed_from_sheets()
    print(f"[run_releases] {len(processed_subjects)} entradas já na planilha (dedup persistente).", file=sys.stderr)

    resultados = []
    for email in emails:
        resultado = processar_email(email, dry_run=args.dry_run, processed_subjects=processed_subjects)
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
