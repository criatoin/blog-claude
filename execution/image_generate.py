"""
image_generate.py — Gera imagem de capa quando não há anexo adequado.

Sequência de tentativas:
  1. Unsplash (grátis) — requer UNSPLASH_ACCESS_KEY
  2. Gemini image generation — requer GEMINI_API_KEY
  3. GPT Image 1 (OpenAI) — requer OPENAI_API_KEY

Após gerar, passa pela mesma pipeline do image_process.py → 1920x1080 WebP <1MB

Uso:
    python execution/image_generate.py --query "festival jazz americana sp" --slug festival-jazz [--output-dir .tmp]

Saída JSON para stdout:
    {"path": ".tmp/festival-jazz_cover.webp", "source": "unsplash", "credit": "Foto: John Doe via Unsplash"}
"""

import argparse
import json
import os
import sys
import tempfile
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

def _try_unsplash(query: str, slug: str, output_dir: str) -> dict | None:
    api_key = os.getenv("UNSPLASH_ACCESS_KEY", "")
    if not api_key:
        print("Unsplash: UNSPLASH_ACCESS_KEY não configurado, pulando.", file=sys.stderr)
        return None

    try:
        resp = requests.get(
            "https://api.unsplash.com/search/photos",
            params={"query": query, "per_page": 5, "orientation": "landscape"},
            headers={"Authorization": f"Client-ID {api_key}"},
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])

        if not results:
            # Fallback: tenta com as 3 primeiras palavras (remove nomes de cidades BR)
            short_query = " ".join(query.split()[:3])
            if short_query != query:
                print(f"Unsplash: sem resultados para '{query}', tentando '{short_query}'", file=sys.stderr)
                resp2 = requests.get(
                    "https://api.unsplash.com/search/photos",
                    params={"query": short_query, "per_page": 5, "orientation": "landscape"},
                    headers={"Authorization": f"Client-ID {api_key}"},
                    timeout=15,
                )
                resp2.raise_for_status()
                results = resp2.json().get("results", [])
            if not results:
                print(f"Unsplash: sem resultados para '{query}'", file=sys.stderr)
                return None

        photo = results[0]
        download_url = photo["urls"]["regular"]  # 1080px de largura
        photographer = photo["user"]["name"]

        img_resp = requests.get(download_url, timeout=30)
        img_resp.raise_for_status()

        raw_path = _save_raw(img_resp.content, slug, output_dir)
        cover_path = _process_to_cover(raw_path, slug, output_dir)

        # Aciona o download tracking do Unsplash (exigido pelos termos)
        try:
            track_url = photo["links"].get("download_location", "")
            if track_url:
                requests.get(track_url, headers={"Authorization": f"Client-ID {api_key}"}, timeout=5)
        except Exception:
            pass

        return {
            "path": cover_path,
            "source": "unsplash",
            "credit": f"Foto: {photographer} via Unsplash",
        }

    except Exception as e:
        print(f"Unsplash falhou: {e}", file=sys.stderr)
        return None


# ─── Fonte 2: Gemini image generation ────────────────────────────────────────

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


# ─── Fonte 3: GPT Image 1 (OpenAI) ───────────────────────────────────────────

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


def generate_image(query: str, slug: str, output_dir: str = ".tmp") -> dict:
    """Tenta Unsplash → Gemini → OpenAI → placeholder PIL. Retorna resultado da primeira que funcionar."""
    for attempt in [_try_unsplash, _try_gemini, _try_openai]:
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
    parser.add_argument("--output-dir", default=".tmp", help="Diretório de saída (padrão: .tmp)")
    args = parser.parse_args()

    result = generate_image(args.query, args.slug, args.output_dir)
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
