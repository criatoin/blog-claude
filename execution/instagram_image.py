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
    """Usa Gemini para gerar arte IG com base na capa e no modelo de referência."""
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY não configurado")

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise RuntimeError("google-genai não instalado")

    client = genai.Client(api_key=api_key)
    model_name = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")

    # Carrega imagens como PIL para enviar ao Gemini
    cover_img = Image.open(cover_path).convert("RGB")
    model_img = Image.open(model_path).convert("RGB")

    prompt = (
        f"Create an Instagram post image (portrait 4:5 ratio) for a cultural portal called '+blog'. "
        f"Use the reference template image as style guide (layout, colors, typography style). "
        f"Use the cover photo as the main visual element. "
        f"The post is about: '{title}'. "
        f"Keep the visual identity of the reference template. "
        f"No text overlays needed — focus on a clean, editorial look."
    )

    response = client.models.generate_content(
        model=model_name,
        contents=[prompt, cover_img, model_img],
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio="4:5"),
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


def _fallback_composite(cover_path: str, model_path: str, slug: str, output_dir: str) -> str:
    """
    Fallback quando Gemini não está disponível:
    Faz um composite simples — modelo de referência no topo, capa na parte inferior.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    model_img = Image.open(model_path).convert("RGB")
    cover_img = Image.open(cover_path).convert("RGB")

    # Modelo ocupa 60% do topo, capa os 40% de baixo
    top_h = int(IG_H * 0.60)
    bot_h = IG_H - top_h

    top = _smart_crop(model_img, IG_W, top_h)
    bot = _smart_crop(cover_img, IG_W, bot_h)

    canvas = Image.new("RGB", (IG_W, IG_H))
    canvas.paste(top, (0, 0))
    canvas.paste(bot, (0, top_h))

    raw_path = out_dir / f"{slug}_ig_raw.jpg"
    canvas.save(str(raw_path), format="JPEG", quality=90)
    return str(raw_path)


def generate_ig_image(cover_path: str, model_path: str, title: str, slug: str, output_dir: str = ".tmp") -> dict:
    dest = Path(output_dir) / f"{slug}_ig.webp"

    # Tenta Gemini, cai no composite se falhar
    try:
        raw_path = _generate_with_gemini(cover_path, model_path, title, slug, output_dir)
        print("Arte IG gerada via Gemini.", file=sys.stderr)
    except Exception as e:
        print(f"Gemini falhou ({e}), usando composite de fallback.", file=sys.stderr)
        raw_path = _fallback_composite(cover_path, model_path, slug, output_dir)

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
