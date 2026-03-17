"""
image_generate.py — Gera imagem de capa quando não há anexo adequado.

Sequência de tentativas:
  1. Unsplash (grátis) — requer UNSPLASH_ACCESS_KEY
  2. Pexels (grátis) — requer PEXELS_API_KEY
  3. Gemini image generation — requer GEMINI_API_KEY
  4. GPT Image 1 (OpenAI) — requer OPENAI_API_KEY

Após gerar, passa pela mesma pipeline do image_process.py → 1920x1080 WebP <1MB

Uso:
    python execution/image_generate.py --query "festival jazz americana sp" --slug festival-jazz --titulo "Festival de Jazz em Americana" [--output-dir .tmp]

Saída JSON para stdout:
    {"path": ".tmp/festival-jazz_cover.webp", "source": "unsplash", "credit": "Foto: John Doe via Unsplash"}
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

# Importação lazy para não falhar se pacotes não estiverem instalados
def _import_genai():
    try:
        from google import genai
        from google.genai import types
        return genai, types
    except ImportError:
        return None, None

def _import_openai():
    try:
        from openai import OpenAI
        return OpenAI
    except ImportError:
        return None


# ─── Validação via Gemini Vision ──────────────────────────────────────────────

def _validate_image(image_path: str, titulo: str) -> bool:
    """
    Usa Gemini Vision para validar imagem antes de aceitar.
    Rejeita se: não é foto real, não é relevante ao título, ou tem texto/banner visível.
    Sem GEMINI_API_KEY: aceita sem validar (apenas loga aviso).
    """
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return True  # sem chave, aceita sem validar

    try:
        from google import genai
        from google.genai import types
        from PIL import Image as PILImage
        import io

        client = genai.Client(api_key=api_key)
        img = PILImage.open(image_path).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        img_bytes = buf.getvalue()

        prompt = (
            f"Analyze this image in strict sequential steps. Answer ONLY 'yes' or 'no'.\n\n"
            f"STEP 1 — IMAGE TYPE (check first, immediately):\n"
            f"Is this image a logo, wordmark, brand identity, graphic design, illustration, flyer, poster, "
            f"banner, infographic, or any image where text or brand elements are the PRIMARY visual content?\n"
            f"→ If YES: answer 'no' IMMEDIATELY. Stop here.\n\n"
            f"STEP 2 — TEXT CONTENT (only if Step 1 passed):\n"
            f"Does the image have text DIGITALLY OVERLAID on top of it (watermarks, title cards, "
            f"captions, promotional text added in post-production)? "
            f"Text that appears NATURALLY in the photographed scene is fine — "
            f"banners at events, signs in the background, text on clothing, text on buildings. "
            f"Only reject if text was ADDED ON TOP of the photo after it was taken.\n"
            f"→ If digitally overlaid text: answer 'no'. Stop here.\n\n"
            f"STEP 3 — CULTURAL CONTEXT (only if Steps 1 and 2 passed):\n"
            f"This image will be used on a Brazilian news blog about events in São Paulo state, Brazil. "
            f"If the image shows people, do they appear in a cultural context clearly incompatible with Brazil? "
            f"Reject if you can clearly identify: hijabs or Islamic dress, saris or South Asian traditional clothing, "
            f"East Asian traditional costumes, African tribal dress, or any other cultural markers that would make "
            f"a Brazilian reader immediately think 'this is not from Brazil or Latin America'. "
            f"Neutral/universal settings (concert stages, gyms, classrooms, offices) are fine regardless of ethnicity. "
            f"Diverse casual clothing is fine. Only reject if cultural dress markers are CLEARLY and PROMINENTLY visible.\n"
            f"→ If clearly culturally incompatible: answer 'no'. Stop here.\n\n"
            f"STEP 4 — RELEVANCE (only if Steps 1, 2 and 3 passed):\n"
            f"Is this a real photograph visually related to: '{titulo}'?\n"
            f"→ If NO: answer 'no'.\n"
            f"→ If YES: answer 'yes'."
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                prompt,
                types.Part(inline_data=types.Blob(mime_type="image/jpeg", data=img_bytes)),
            ],
        )
        answer = response.text.strip().lower()
        valid = answer.startswith("yes")
        if not valid:
            print(f"[image_generate] Imagem rejeitada pela vision (não-foto/irrelevante/texto): {image_path}", file=sys.stderr)
        return valid

    except Exception as e:
        print(f"[image_generate] Aviso: validação vision falhou ({e}), aceitando imagem.", file=sys.stderr)
        return True  # em erro, aceita (já é fallback)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _process_to_cover(raw_path: str, slug: str, output_dir: str) -> str:
    """Aplica image_process.py internamente e retorna o path do cover final."""
    # Importa diretamente para evitar subprocess
    sys.path.insert(0, str(Path(__file__).parent))
    from image_process import process_image
    result = process_image(raw_path, slug, output_dir)
    return result["path"]


def _save_raw(content: bytes, slug: str, output_dir: str, ext: str = "jpg") -> str:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / f"{slug}_raw.{ext}"
    raw_path.write_bytes(content)
    return str(raw_path)


# ─── Fonte 1: Unsplash ────────────────────────────────────────────────────────

def _try_unsplash(query: str, slug: str, output_dir: str, titulo: str = "") -> dict | None:
    api_key = os.getenv("UNSPLASH_ACCESS_KEY", "")
    if not api_key:
        print("Unsplash: UNSPLASH_ACCESS_KEY não configurado, pulando.", file=sys.stderr)
        return None

    def _search(q: str) -> list:
        r = requests.get(
            "https://api.unsplash.com/search/photos",
            params={"query": q, "per_page": 5, "orientation": "landscape"},
            headers={"Authorization": f"Client-ID {api_key}"},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("results", [])

    try:
        results = _search(query)

        if not results:
            short_query = " ".join(query.split()[:3])
            if short_query != query:
                print(f"Unsplash: sem resultados para '{query}', tentando '{short_query}'", file=sys.stderr)
                results = _search(short_query)
            if not results:
                print(f"Unsplash: sem resultados para '{query}'", file=sys.stderr)
                return None

        # Itera pelos candidatos e usa o primeiro que passar na validação
        for idx, photo in enumerate(results):
            download_url = photo["urls"]["regular"]  # 1080px de largura
            photographer = photo["user"]["name"]

            img_resp = requests.get(download_url, timeout=30)
            img_resp.raise_for_status()

            raw_path = _save_raw(img_resp.content, slug, output_dir)

            if titulo and not _validate_image(raw_path, titulo):
                print(f"Unsplash: candidato {idx+1}/5 rejeitado, tentando próximo.", file=sys.stderr)
                continue

            cover_path = _process_to_cover(raw_path, slug, output_dir)

            # Aciona o download tracking do Unsplash (exigido pelos termos)
            try:
                track_url = photo["links"].get("download_location", "")
                if track_url:
                    requests.get(track_url, headers={"Authorization": f"Client-ID {api_key}"}, timeout=5)
            except Exception:
                pass

            print(f"Unsplash: candidato {idx+1}/5 aprovado.", file=sys.stderr)
            return {
                "path": cover_path,
                "source": "unsplash",
                "credit": f"Foto: {photographer} via Unsplash",
            }

        print(f"Unsplash: nenhum dos {len(results)} candidatos passou na validação.", file=sys.stderr)
        return None

    except Exception as e:
        print(f"Unsplash falhou: {e}", file=sys.stderr)
        return None


# ─── Fonte 2: Pexels ─────────────────────────────────────────────────────────

def _try_pexels(query: str, slug: str, output_dir: str, titulo: str = "") -> dict | None:
    api_key = os.getenv("PEXELS_API_KEY", "")
    if not api_key:
        print("Pexels: PEXELS_API_KEY não configurado, pulando.", file=sys.stderr)
        return None

    def _search(q: str) -> list:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            params={"query": q, "per_page": 5, "orientation": "landscape"},
            headers={"Authorization": api_key},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("photos", [])

    try:
        photos = _search(query)

        if not photos:
            short_query = " ".join(query.split()[:3])
            if short_query != query:
                print(f"Pexels: sem resultados para '{query}', tentando '{short_query}'", file=sys.stderr)
                photos = _search(short_query)
            if not photos:
                print(f"Pexels: sem resultados para '{query}'", file=sys.stderr)
                return None

        # Itera pelos candidatos e usa o primeiro que passar na validação
        for idx, photo in enumerate(photos):
            download_url = photo["src"]["large2x"]  # ~1880px de largura
            photographer = photo.get("photographer", "")

            img_resp = requests.get(download_url, timeout=30)
            img_resp.raise_for_status()

            raw_path = _save_raw(img_resp.content, slug, output_dir)

            if titulo and not _validate_image(raw_path, titulo):
                print(f"Pexels: candidato {idx+1}/5 rejeitado, tentando próximo.", file=sys.stderr)
                continue

            cover_path = _process_to_cover(raw_path, slug, output_dir)

            print(f"Pexels: candidato {idx+1}/5 aprovado.", file=sys.stderr)
            return {
                "path": cover_path,
                "source": "pexels",
                "credit": f"Foto: {photographer} via Pexels" if photographer else "",
            }

        print(f"Pexels: nenhum dos {len(photos)} candidatos passou na validação.", file=sys.stderr)
        return None

    except Exception as e:
        print(f"Pexels falhou: {e}", file=sys.stderr)
        return None


# ─── Fonte 3: Gemini image generation ───────────────────────────────────────

def _try_gemini(query: str, slug: str, output_dir: str) -> dict | None:
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        print("Gemini: GEMINI_API_KEY não configurado, pulando.", file=sys.stderr)
        return None

    genai, types = _import_genai()
    if genai is None:
        print("Gemini: google-genai não instalado, pulando.", file=sys.stderr)
        return None

    try:
        client = genai.Client(api_key=api_key)
        model_name = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")

        prompt = (
            f"Create a high-quality landscape photograph for a news article cover. "
            f"Subject: {query}. "
            f"Style: editorial photography, natural lighting, vibrant colors. "
            f"IMPORTANT: absolutely no text, no signs, no banners, no writing, no logos, "
            f"no labels, no captions anywhere in the image. Pure photography only."
        )

        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(aspect_ratio="16:9"),
            ),
        )

        # Extrai bytes da imagem da resposta
        img_bytes = None
        for part in response.parts:
            if part.inline_data:
                img_bytes = part.inline_data.data
                break

        if not img_bytes:
            print("Gemini: resposta sem dados de imagem.", file=sys.stderr)
            return None

        raw_path = _save_raw(img_bytes, slug, output_dir)
        cover_path = _process_to_cover(raw_path, slug, output_dir)

        return {
            "path": cover_path,
            "source": "gemini",
            "credit": "",
        }

    except Exception as e:
        print(f"Gemini falhou: {e}", file=sys.stderr)
        return None


# ─── Fonte 4: GPT Image 1 (OpenAI) ──────────────────────────────────────────

def _try_openai(query: str, slug: str, output_dir: str) -> dict | None:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        print("OpenAI: OPENAI_API_KEY não configurado, pulando.", file=sys.stderr)
        return None

    OpenAI = _import_openai()
    if OpenAI is None:
        print("OpenAI: pacote openai não instalado, pulando.", file=sys.stderr)
        return None

    try:
        import base64
        client = OpenAI(api_key=api_key)

        prompt = (
            f"Editorial photography for a news article cover. "
            f"Subject: {query}. "
            f"High resolution, natural lighting, landscape orientation. "
            f"IMPORTANT: absolutely no text, no signs, no banners, no writing, no logos, "
            f"no labels anywhere in the image. Pure photography only."
        )

        # gpt-image-1 retorna b64_json por padrão (não aceita response_format)
        response = client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size="1536x1024",
            quality="medium",
            n=1,
        )

        b64_data = response.data[0].b64_json
        img_bytes = base64.b64decode(b64_data)

        raw_path = _save_raw(img_bytes, slug, output_dir, ext="png")
        cover_path = _process_to_cover(raw_path, slug, output_dir)

        return {
            "path": cover_path,
            "source": "openai",
            "credit": "",
        }

    except Exception as e:
        print(f"OpenAI falhou: {e}", file=sys.stderr)
        return None


# ─── Orquestrador ─────────────────────────────────────────────────────────────

def _try_pil_placeholder(slug: str, output_dir: str) -> dict | None:
    """Último recurso: gera imagem placeholder sólida via PIL (sem API). Sempre funciona."""
    try:
        from PIL import Image as PILImage
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        img = PILImage.new("RGB", (1920, 1080), color=(45, 55, 72))
        raw_path = str(out_dir / f"{slug}_raw.jpg")
        img.save(raw_path, format="JPEG", quality=85)
        cover_path = _process_to_cover(raw_path, slug, output_dir)
        print(f"Placeholder PIL gerado como fallback final.", file=sys.stderr)
        return {"path": cover_path, "source": "placeholder", "credit": ""}
    except Exception as e:
        print(f"Placeholder PIL falhou: {e}", file=sys.stderr)
        return None


def generate_image(query: str, slug: str, output_dir: str = ".tmp", titulo: str = "") -> dict:
    """Tenta Unsplash → Pexels → Gemini → OpenAI → placeholder PIL. Retorna resultado da primeira que funcionar."""
    for attempt in [
        lambda q, s, o: _try_unsplash(q, s, o, titulo),
        lambda q, s, o: _try_pexels(q, s, o, titulo),
        _try_gemini,
        _try_openai,
    ]:
        result = attempt(query, slug, output_dir)
        if result:
            return result

    print("Aviso: todas as fontes de imagem falharam. Usando placeholder PIL.", file=sys.stderr)
    result = _try_pil_placeholder(slug, output_dir)
    if result:
        return result

    print("Erro crítico: nem o placeholder PIL funcionou.", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera imagem de capa via Unsplash/Gemini/OpenAI")
    parser.add_argument("--query", required=True, help="Descrição do tema para busca/geração")
    parser.add_argument("--slug", required=True, help="Slug do post")
    parser.add_argument("--titulo", default="", help="Título do artigo — usado para validação via Gemini Vision")
    parser.add_argument("--output-dir", default=".tmp", help="Diretório de saída (padrão: .tmp)")
    args = parser.parse_args()

    result = generate_image(args.query, args.slug, args.output_dir, args.titulo)
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
