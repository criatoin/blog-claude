"""
image_process.py — Redimensiona e converte imagem para capa 1920x1080 WebP <1MB.

Lógica:
  1. Smart crop centralizado para 1920x1080 (mantém proporção, corta excesso)
  2. Salva como WebP com qualidade 85 → 75 → 65 até ficar <1MB

Uso:
    python execution/image_process.py --input .tmp/img.jpg --slug meu-post [--output-dir .tmp]

Saída JSON para stdout:
    {"path": ".tmp/meu-post_cover.webp", "size_kb": 856, "width": 1920, "height": 1080}
"""

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

TARGET_W, TARGET_H = 1920, 1080
TARGET_RATIO = TARGET_W / TARGET_H  # 1.778
MAX_SIZE_BYTES = 1 * 1024 * 1024   # 1 MB
QUALITY_STEPS = [85, 75, 65, 55]


def smart_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Redimensiona mantendo proporção e faz crop centralizado."""
    src_w, src_h = img.size
    src_ratio = src_w / src_h
    target_ratio = target_w / target_h

    if src_ratio > target_ratio:
        # Imagem mais larga que o alvo — ajusta pela altura, corta largura
        new_h = target_h
        new_w = int(src_w * (target_h / src_h))
    else:
        # Imagem mais alta que o alvo — ajusta pela largura, corta altura
        new_w = target_w
        new_h = int(src_h * (target_w / src_w))

    img = img.resize((new_w, new_h), Image.LANCZOS)

    # Crop centralizado
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    img = img.crop((left, top, left + target_w, top + target_h))

    return img


def process_image(input_path: str, slug: str, output_dir: str = ".tmp") -> dict:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{slug}_cover.webp"

    with Image.open(input_path) as img:
        # Converte para RGB (WebP não suporta RGBA com método padrão)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        cropped = smart_crop(img, TARGET_W, TARGET_H)

        for quality in QUALITY_STEPS:
            cropped.save(str(dest), format="WEBP", quality=quality, method=6)
            size = dest.stat().st_size
            if size <= MAX_SIZE_BYTES:
                break

    final_size = dest.stat().st_size
    return {
        "path": str(dest),
        "size_kb": round(final_size / 1024, 1),
        "width": TARGET_W,
        "height": TARGET_H,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Processa imagem para capa 1920x1080 WebP")
    parser.add_argument("--input", required=True, help="Caminho da imagem de entrada")
    parser.add_argument("--slug", required=True, help="Slug do post (usado no nome do arquivo)")
    parser.add_argument("--output-dir", default=".tmp", help="Diretório de saída (padrão: .tmp)")
    args = parser.parse_args()

    result = process_image(args.input, args.slug, args.output_dir)
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
