"""
instagram_image.py — Gera arte para Instagram combinando modelo de referência
e imagem de capa via Gemini image generation.

Formato de saída: 1080x1350px (4:5), WebP, <1MB

Uso:
    python execution/instagram_image.py \
        --cover .tmp/slug_cover.webp \
        --model assets/instagram/6.jpg \
        --slug meu-post \
        --title "Título do evento" \
        [--output-dir .tmp]

Saída JSON para stdout:
    {"path": ".tmp/meu-post_ig.webp", "size_kb": 420}
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image

load_dotenv()

IG_W, IG_H = 1080, 1350
MAX_SIZE_BYTES = 1 * 1024 * 1024
QUALITY_STEPS = [85, 75, 65, 55]


def _compress_webp(img: Image.Image, dest: Path) -> None:
    for quality in QUALITY_STEPS:
        img.save(str(dest), format="WEBP", quality=quality, method=6)
        if dest.stat().st_size <= MAX_SIZE_BYTES:
            break


def _smart_crop(img: Image.Image, w: int, h: int) -> Image.Image:
    src_w, src_h = img.size
    ratio = w / h
    src_ratio = src_w / src_h

    if src_ratio > ratio:
        new_h = h
        new_w = int(src_w * h / src_h)
    else:
        new_w = w
        new_h = int(src_h * w / src_w)

    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - w) // 2
    top = (new_h - h) // 2
    return img.crop((left, top, left + w, top + h))


def _generate_with_gemini(cover_path: str, model_path: str, title: str, slug: str, output_dir: str) -> str:
    """Usa Gemini para gerar arte IG a partir da imagem de capa."""
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY não configurado")

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise RuntimeError("google-genai não instalado")

    client = genai.Client(api_key=api_key)
    model_name = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.0-flash-preview-image-generation")

    # Envia só a imagem de capa — não mistura com o template
    cover_img = Image.open(cover_path).convert("RGB")

    prompt = (
        f"Transform this image into a vertical Instagram post (4:5 portrait ratio) for '+blog', "
        f"a Brazilian cultural portal covering events in Americana and region (SP). "
        f"The post is about: '{title}'. "
        f"Style: editorial, clean, vibrant. Keep the main subject centered. "
        f"No text overlays. Output a single polished image ready for Instagram."
    )

    response = client.models.generate_content(
        model=model_name,
        contents=[prompt, cover_img],
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
        ),
    )

    img_bytes = None
    for part in response.parts:
        if part.inline_data:
            img_bytes = part.inline_data.data
            break

    if not img_bytes:
        raise RuntimeError("Gemini não retornou dados de imagem")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / f"{slug}_ig_raw.jpg"
    raw_path.write_bytes(img_bytes)
    return str(raw_path)


def _fallback_portrait_crop(cover_path: str, slug: str, output_dir: str) -> str:
    """
    Fallback quando Gemini não está disponível:
    Faz um crop inteligente da capa para formato portrait 4:5.
    Sem misturar com template — resultado limpo.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cover_img = Image.open(cover_path).convert("RGB")
    cropped = _smart_crop(cover_img, IG_W, IG_H)

    raw_path = out_dir / f"{slug}_ig_raw.jpg"
    cropped.save(str(raw_path), format="JPEG", quality=90)
    return str(raw_path)


def generate_ig_image(cover_path: str, model_path: str, title: str, slug: str, output_dir: str = ".tmp") -> dict:
    dest = Path(output_dir) / f"{slug}_ig.webp"

    # Tenta Gemini; fallback = crop portrait da capa (sem mistura com template)
    try:
        raw_path = _generate_with_gemini(cover_path, model_path, title, slug, output_dir)
        print("Arte IG gerada via Gemini.", file=sys.stderr)
    except Exception as e:
        print(f"Gemini falhou ({e}), usando crop portrait como fallback.", file=sys.stderr)
        raw_path = _fallback_portrait_crop(cover_path, slug, output_dir)

    # Processa para o formato final
    with Image.open(raw_path) as img:
        if img.mode != "RGB":
            img = img.convert("RGB")
        final = _smart_crop(img, IG_W, IG_H)
        _compress_webp(final, dest)

    return {
        "path": str(dest),
        "size_kb": round(dest.stat().st_size / 1024, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera arte Instagram 1080x1350 WebP")
    parser.add_argument("--cover", required=True, help="Caminho da imagem de capa do post")
    parser.add_argument("--model", required=True, help="Modelo de referência do Instagram")
    parser.add_argument("--slug", required=True, help="Slug do post")
    parser.add_argument("--title", required=True, help="Título do post")
    parser.add_argument("--output-dir", default=".tmp")
    args = parser.parse_args()

    result = generate_ig_image(args.cover, args.model, args.title, args.slug, args.output_dir)
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
