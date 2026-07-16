"""
run_releases.py — Pipeline autônomo de releases: Gmail → WP rascunho → Telegram.

Fluxo:
  1. gmail_fetch.py → lista de emails não lidos
  2. Para cada email: llm_call() avalia relevância → não relevante: pula
  3. llm_call() reescreve post → JSON {titulo, slug, html, wp_category_id, credito_imagem}
  4. Dedup por slug: wp_publish.py find --slug <slug> (já existe no WP? pula)
  5. Pipeline imagem: image_select.py (anexos) → image_process.py ou image_generate.py
  6. instagram_image.py + legenda via llm_call()
  7. wp_publish.py create --category-id <id>
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


def _imagem_adequada_para_arte(image_path: str) -> bool:
    """Verifica resolução mínima sem LLM. Rejeita imagens pequenas demais."""
    try:
        from PIL import Image as _PILImage
        with _PILImage.open(image_path) as img:
            w, h = img.size
            return w >= 800 and h >= 600
    except Exception:
        return False


def _imagem_relevante(image_path: str, titulo: str) -> str:
    """
    Usa Gemini Vision para verificar se a imagem é relevante ao título do post.
    Retorna "yes" (relevante), "no" (não relevante → cai para Unsplash/Gemini) ou
    "unavailable" (vision não pôde rodar — sem GEMINI_API_KEY ou 503). "unavailable"
    NUNCA deve ser tratado como aprovação automática pelo chamador.
    """
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return "unavailable"  # sem chave, não dá para verificar

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
            f"This image came attached to a press release from a Brazilian cultural event. "
            f"Answer ONLY 'yes' (accept) or 'no' (reject).\n\n"
            f"ACCEPT the image if ANY of these are true:\n"
            f"- It contains real people (even if standing in front of a banner, sign, or poster)\n"
            f"- It shows a real place or venue relevant to the event\n"
            f"- It is a real photograph, even if it has text overlays, logos, or event banners in the background\n\n"
            f"REJECT the image ONLY if ALL of these are true:\n"
            f"- There are NO real people visible in the photo\n"
            f"- The image is purely a graphic: flyer, poster, digital art, logo, or infographic with no photographic content\n\n"
            f"Post title for context: '{titulo}'\n\n"
            f"IMPORTANT: A photo of people standing in front of an event banner is a REAL PHOTO — accept it. "
            f"Only reject pure graphic design with zero photographic content."
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
        veredito = words[-1] if words else "no"
        if veredito == "no":
            print(f"[run_releases] Imagem rejeitada (logo/não-foto/irrelevante) para '{titulo[:50]}' — usando Unsplash/Gemini.", file=sys.stderr)
        else:
            print(f"[run_releases] Imagem aprovada pela vision para '{titulo[:50]}'.", file=sys.stderr)
        return veredito

    except Exception as e:
        err_str = str(e)
        is_server_overload = (
            "'code': 503" in err_str
            or '"code": 503' in err_str
            or "503 UNAVAILABLE" in err_str
        )
        if is_server_overload:
            print(f"[run_releases] Vision API indisponível (503), foto do email vira sugestão não-validada.", file=sys.stderr)
            return "unavailable"
        print(f"[run_releases] Aviso: verificação de relevância falhou ({e}), rejeitando imagem por precaução.", file=sys.stderr)
        return "no"


def _pipeline_imagem(email: dict, slug: str, titulo: str = "", fatos: dict | None = None) -> dict:
    """
    Seleciona imagem de capa. Prioridade: fotos do email > banco de imagens.
    Retorna dict:
      cover_path        — capa aprovada ("" se nenhuma)
      credit            — crédito da capa
      suggestion_path   — melhor candidata NÃO validada (para o card de pendência)
      suggestion_credit — crédito da sugestão
    """
    if fatos is None:
        fatos = {}
    vazio = {"cover_path": "", "credit": "", "suggestion_path": "", "suggestion_credit": ""}
    attachments = email.get("attachments", [])
    sugestao_path, sugestao_credit = "", ""

    if attachments:
        scored = []
        for att in attachments:
            r = _run_json([str(SCRIPT_DIR / "image_select.py"), "--images", att])
            if r and r.get("score", -1) >= 0:
                scored.append(r)
        scored.sort(key=lambda x: x.get("score", 0), reverse=True)
        print(f"[run_releases] {len(scored)} foto(s) do email para avaliar.", file=sys.stderr)

        for candidate in scored:
            cpath = candidate.get("path")
            if not cpath or not _imagem_adequada_para_arte(cpath):
                continue
            veredito = _imagem_relevante(cpath, titulo) if titulo else "yes"
            if veredito == "no":
                print(f"[run_releases] Foto rejeitada (vision): {Path(cpath).name}", file=sys.stderr)
                continue
            proc_result = _run_json([
                str(SCRIPT_DIR / "image_process.py"),
                "--input", cpath, "--slug", slug, "--output-dir", OUTPUT_DIR,
            ])
            if not proc_result or not proc_result.get("path"):
                continue
            if veredito == "unavailable":
                # Vision fora do ar: foto do email vira sugestão, não capa automática
                if not sugestao_path:
                    sugestao_path, sugestao_credit = proc_result["path"], ""
                    print(f"[run_releases] Vision indisponível — foto vira sugestão.", file=sys.stderr)
                continue
            print(f"[run_releases] Usando foto do email: {Path(cpath).name}", file=sys.stderr)
            return {**vazio, "cover_path": proc_result["path"]}

        print(f"[run_releases] Nenhuma foto do email aprovada.", file=sys.stderr)

    # Banco de imagens (Unsplash/Pexels/IA)
    from editorial import query_from_fatos
    img_query = query_from_fatos(fatos, titulo)
    print(f"[run_releases] Buscando em bancos | query='{img_query}'...", file=sys.stderr)
    gen_result = _run_json([
        str(SCRIPT_DIR / "image_generate.py"),
        "--query", img_query, "--slug", slug,
        "--titulo", titulo, "--output-dir", OUTPUT_DIR,
    ])
    if gen_result and gen_result.get("path"):
        if gen_result.get("validated"):
            return {**vazio,
                    "cover_path": gen_result["path"],
                    "credit": gen_result.get("credit", "")}
        # Candidato não validado — vira sugestão (se ainda não temos uma do email)
        if not sugestao_path:
            sugestao_path = gen_result["path"]
            sugestao_credit = gen_result.get("credit", "")

    return {**vazio, "suggestion_path": sugestao_path, "suggestion_credit": sugestao_credit}


def processar_email(email: dict, dry_run: bool = False) -> dict:
    """Processa um email pelo pipeline completo. Retorna dict com resultado."""
    from editorial import (
        extrair_fatos, avaliar_relevancia, extract_editorial_hierarchy,
        gerar_arte_com_validacao, gerar_legenda,
        validate_instagram_output_against_hierarchy,
        validar_fatos, resumo_telegram,
    )

    email_id = email.get("id", "?")
    subject = email.get("subject", "")
    sender = email.get("sender", "")
    date = email.get("date", "")
    body_text = email.get("body_text", "") or email.get("body_html", "")[:8000]

    # Deduplicação: arquivo local
    if not dry_run and email_id in _load_processed():
        print(f"\n[run_releases] → Já processado (arquivo), pulando: {subject[:60]}", file=sys.stderr)
        return {"email_id": email_id, "relevante": False, "motivo": "Já processado anteriormente"}

    print(f"\n[run_releases] → Processando: {subject[:60]}", file=sys.stderr)

    # 1. Extrai fatos
    print(f"[run_releases]   1/7 Extraindo fatos...", file=sys.stderr)
    fatos = extrair_fatos(body_text)

    # 2. Avalia relevância
    print(f"[run_releases]   2/7 Avaliando relevância...", file=sys.stderr)
    avaliacao = avaliar_relevancia(body_text, fatos)
    relevante = avaliacao.get("relevante", False)

    if not relevante:
        motivo = avaliacao.get("motivo_aprovacao_ou_descarte", "Não relevante")
        print(f"[run_releases]   Não relevante: {motivo}", file=sys.stderr)
        return {"email_id": email_id, "relevante": False, "motivo": motivo}

    # 3. Hierarquia editorial — define foco antes de gerar arte e legenda
    print(f"[run_releases]   3/7 Definindo hierarquia editorial...", file=sys.stderr)
    hierarchy = extract_editorial_hierarchy(body_text, fatos)
    print(f"[run_releases]   Foco: {hierarchy.get('foco_principal', '')[:80]}", file=sys.stderr)
    if hierarchy.get("atividades_passadas"):
        print(f"[run_releases]   Passadas (excluir do foco): {hierarchy['atividades_passadas']}", file=sys.stderr)

    # 4. Gera conteúdo editorial com validação e retentativa automática
    print(f"[run_releases]   4/7 Gerando conteúdo...", file=sys.stderr)
    post = gerar_arte_com_validacao(
        body_text, fatos, avaliacao, sender=sender,
        release_titulo=subject, hierarchy=hierarchy,
    )

    titulo = post.get("titulo_site") or subject[:65]
    slug = post.get("slug") or "post-sem-slug"
    html = post.get("html", "")
    wp_category_id = post.get("wp_category_id", 12)
    if wp_category_id not in VALID_CATEGORY_IDS:
        print(f"[run_releases]   Categoria inválida ({wp_category_id}), usando Eventos (12).", file=sys.stderr)
        wp_category_id = 12
    tags = post.get("tags", [])
    creditos = post.get("creditos_wordpress", {})

    print(f"[run_releases]   Título: {titulo}", file=sys.stderr)

    if dry_run:
        return {"email_id": email_id, "relevante": True, "titulo": titulo, "slug": slug, "dry_run": True}

    # Dedup persistente: já existe post com este slug no WP?
    existente = _run_json([str(SCRIPT_DIR / "wp_publish.py"), "find", "--slug", slug])
    if existente and existente.get("exists"):
        print(f"[run_releases]   Post já existe no WP (#{existente['post_id']}), pulando.", file=sys.stderr)
        _mark_processed(email_id)
        return {"email_id": email_id, "relevante": True, "motivo": "Duplicado no WP"}

    # 4. Pipeline de imagem (usa fatos para query — sem LLM extra)
    img = _pipeline_imagem(email, slug, titulo, fatos=fatos)
    cover_path = img["cover_path"]
    foto_credit_gerada = img["credit"]

    # Crédito de foto: release > gerada > Divulgação
    foto_credit = creditos.get("fotos") or foto_credit_gerada or "Divulgação"

    # 5. Arte Instagram
    ig_path = ""
    ig_url = ""
    if cover_path and Path(cover_path).exists():
        category_name = CATEGORY_NAMES.get(wp_category_id, "Eventos")
        art_title = post.get("texto_arte", {}).get("titulo_principal", "") or titulo
        art_subtitle = post.get("texto_arte", {}).get("linha_apoio", "")
        ig_args = [
            str(SCRIPT_DIR / "instagram_image.py"),
            "--cover", cover_path,
            "--slug", slug,
            "--title", titulo,
            "--category", category_name,
            "--output-dir", OUTPUT_DIR,
        ]
        if art_title:
            ig_args += ["--art-title", art_title]
        if art_subtitle:
            ig_args += ["--art-subtitle", art_subtitle]
        ig_result = _run_json(ig_args)
        if ig_result:
            ig_path = ig_result.get("path", "")

    # Upload da arte IG para WP
    if ig_path and Path(ig_path).exists():
        upload_result = _run_json([
            str(SCRIPT_DIR / "wp_publish.py"), "upload-image",
            "--image-path", ig_path,
            "--title", f"{titulo} — Instagram",
        ])
        if upload_result:
            ig_url = upload_result.get("url", "")

    # 5. Legenda Instagram (sem créditos — exclusivos do WP)
    print(f"[run_releases]   5/7 Gerando legenda IG...", file=sys.stderr)
    legendas = gerar_legenda(
        fatos, post.get("resumo_telegram", ""),
        arte_instagram=post.get("texto_arte"),
        hierarchy=hierarchy,
    )
    legenda_curta = legendas.get("legenda_curta", "")
    legenda_longa = legendas.get("legenda_contexto", "")

    # Valida saída de arte e legenda contra a hierarquia editorial
    erros_hierarquia = validate_instagram_output_against_hierarchy(
        post.get("texto_arte", {}), legendas, hierarchy, fatos
    )
    if erros_hierarquia:
        print(f"[run_releases]   Aviso hierarquia: {erros_hierarquia}", file=sys.stderr)

    # 6. Validação factual
    print(f"[run_releases]   6/7 Validando fatos...", file=sys.stderr)
    post_para_validar = {**post, "legenda_curta": legenda_curta}
    validacao = validar_fatos(body_text, fatos, post_para_validar)
    risco = validacao.get("risco_alucinacao", "baixo")
    if risco != "baixo":
        print(f"[run_releases]   Risco de alucinacao: {risco}", file=sys.stderr)

    # 7. Resumo para Telegram
    print(f"[run_releases]   7/7 Montando resumo Telegram...", file=sys.stderr)
    card_meta = resumo_telegram(post, validacao, avaliacao)

    # 9. HTML com bloco de créditos ao final (exclusivo WordPress)
    sender_clean = sender.split("<")[0].strip() or sender.split("@")[0]
    credito_texto = creditos.get("texto", "").strip() or f"reescrito pela equipe do +blog com informações de {sender_clean}"
    creditos_html = f'<p><em>Texto: {credito_texto}. Fotos: {foto_credit}</em></p>'
    html_com_creditos = html + "\n" + creditos_html

    # 10. Publica rascunho no WordPress
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

    _mark_processed(email_id)
    post_id = wp_result.get("post_id")
    edit_url = wp_result.get("edit_url", "")

    # 11. Notifica Telegram com card enriquecido
    if cover_path:
        # Fluxo normal: card completo de aprovação
        notify_args = [
            str(SCRIPT_DIR / "telegram_notify.py"), "send-release",
            "--post-id", str(post_id),
            "--title", titulo,
            "--summary", post.get("resumo_telegram", html[:300].replace("<", "").replace(">", "")[:200]),
            "--edit-url", edit_url,
            "--cover", cover_path,
            "--sheets-row-id", "0",
            "--card-meta", json.dumps(card_meta, ensure_ascii=False),
        ]
        if ig_path:
            notify_args += ["--ig-image", ig_path, "--ig-caption", legenda_curta]
        notify_result = _run(notify_args)
    else:
        # Sem imagem aprovada: card de pendência — humano decide a imagem
        pending_entry = {
            "post_id": post_id,
            "slug": slug,
            "titulo": titulo,
            "category_name": CATEGORY_NAMES.get(wp_category_id, "Eventos"),
            "art_title": post.get("texto_arte", {}).get("titulo_principal", "") or titulo,
            "art_subtitle": post.get("texto_arte", {}).get("linha_apoio", ""),
            "legenda_curta": legenda_curta,
            "legenda_longa": legenda_longa,
            "edit_url": edit_url,
            "summary": post.get("resumo_telegram", ""),
            "card_meta": card_meta,
            "suggestion_path": img["suggestion_path"],
            "suggestion_credit": img["suggestion_credit"],
        }
        notify_result = _run([
            str(SCRIPT_DIR / "telegram_notify.py"), "send-image-pending",
            "--data", json.dumps(pending_entry, ensure_ascii=False),
        ])
    if notify_result.returncode != 0:
        print(f"[run_releases]   Aviso: telegram_notify falhou ({notify_result.returncode}):\n{notify_result.stderr[:300]}", file=sys.stderr)

    print(f"[run_releases]   Rascunho #{post_id} criado. Card enviado ao Telegram.", file=sys.stderr)

    return {
        "email_id": email_id,
        "relevante": True,
        "titulo": titulo,
        "post_id": post_id,
        "risco_alucinacao": risco,
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
