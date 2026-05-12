"""
instagram_image.py — Gera arte para Instagram via composição Pillow.

Template +blog — 4 camadas:
  1. Background full-canvas desfocado (ImageOps.fit + GaussianBlur)
  2. Foto principal fit_width=1080 com fade inferior proporcional
  3. Gradiente overlay (alpha máximo 210, nunca sólido)
  4. Badge + título + subtítulo + logo

Formato: 1080×1350px WebP, <1MB

Uso:
    python execution/instagram_image.py \
        --cover .tmp/slug_cover.webp \
        --slug meu-post \
        --title "Título" \
        --category "Cultura" \
        [--art-subtitle "Linha de apoio"] \
        [--output-dir .tmp]

Saída JSON: {"path": ".tmp/slug_ig.webp", "size_kb": 420}
"""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

load_dotenv()

IG_W, IG_H = 1080, 1350
MAX_SIZE_BYTES = 1 * 1024 * 1024
QUALITY_STEPS  = [85, 75, 65, 55]

PROJECT_DIR = Path(__file__).parent.parent
FONT_BOLD   = str(PROJECT_DIR / "assets" / "fonts" / "Poppins-Bold.ttf")
LOGO_PATH   = str(PROJECT_DIR / "assets" / "logo" / "Logo +blog rosa.png")


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_BOLD, size)
    except Exception:
        return ImageFont.load_default()


def generate_ig_image(
    cover_path: str,
    category: str,
    title: str,
    slug: str,
    output_dir: str = ".tmp",
    subtitle: str = "",
) -> dict:
    W, H = IG_W, IG_H
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{slug}_ig.webp"

    font_badge  = _load_font(26)
    font_titulo = _load_font(86)
    font_sub    = _load_font(36)

    # === CAMADA 1: Background full canvas desfocado ===
    bg = Image.open(cover_path).convert("RGBA")
    bg = ImageOps.fit(bg, (W, H), method=Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=18))
    dark = Image.new("RGBA", (W, H), (0, 0, 0, 65))
    bg = Image.alpha_composite(bg, dark)
    canvas = bg.copy()

    # === CAMADA 2: Foto principal com fade inferior ===
    photo = Image.open(cover_path).convert("RGBA")
    ratio = W / photo.width
    ph = int(photo.height * ratio)
    photo = photo.resize((W, ph), Image.LANCZOS)

    mask = Image.new("L", (W, ph), 255)
    fade_start = int(ph * 0.62)
    for y in range(fade_start, ph):
        v = int(255 * (1 - (y - fade_start) / (ph - fade_start)))
        ImageDraw.Draw(mask).line([(0, y), (W, y)], fill=v)
    photo.putalpha(mask)
    canvas.alpha_composite(photo, (0, 0))

    # === CAMADA 3: Degradê overlay (nunca sólido, alpha máximo 210) ===
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(grad)
    for y in range(H):
        if y < 420:
            draw.line([(0, y), (W, y)], fill=(0, 0, 0, 0))
        elif y < 660:
            p = (y - 420) / (660 - 420)
            a = int(155 * p)
            r = int(130 * p)
            b = int(115 * p)
            draw.line([(0, y), (W, y)], fill=(r, 0, b, a))
        else:
            p = min(1.0, (y - 660) / (H - 660))
            a = int(155 + 55 * p)   # máximo 210
            r = int(100 - 35 * p)
            b = int(130 + 20 * p)
            draw.line([(0, y), (W, y)], fill=(r, 0, b, a))
    canvas.alpha_composite(grad)

    # === CAMADA 4: Texto e logo ===
    d = ImageDraw.Draw(canvas)

    # Badge amarelo
    bx, by = 70, 648
    bbox = d.textbbox((bx, by), category.upper(), font=font_badge)
    pad = 12
    d.rounded_rectangle(
        [bbox[0] - pad, bbox[1] - pad // 2, bbox[2] + pad, bbox[3] + pad // 2],
        radius=6,
        fill=(200, 230, 0),
    )
    d.text((bx, by), category.upper(), font=font_badge, fill=(0, 0, 0))

    # Título com quebra automática
    ty = by + 60
    words = title.split()
    lines: list[str] = []
    line = ""
    for w in words:
        test = (line + " " + w).strip()
        if d.textlength(test, font=font_titulo) < 940:
            line = test
        else:
            lines.append(line)
            line = w
    lines.append(line)
    for l in lines[:3]:
        d.text((70, ty), l, font=font_titulo, fill=(255, 255, 255))
        ty += int(font_titulo.size * 1.1)

    # Subtítulo
    if subtitle:
        d.text((70, ty + 18), subtitle, font=font_sub, fill=(230, 230, 230, 220))

    # Logo — remove fundo branco antes de compor
    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
        data = logo.getdata()
        logo.putdata([
            (r, g, b, 0) if r > 230 and g > 230 and b > 230 else (r, g, b, a)
            for r, g, b, a in data
        ])
        bbox = logo.getbbox()
        if bbox:
            logo = logo.crop(bbox)
        lw = 240
        lh = int(logo.height * lw / logo.width)
        logo = logo.resize((lw, lh), Image.LANCZOS)
        lx = (W - lw) // 2
        ly = H - lh - 65
        canvas.alpha_composite(logo, (lx, ly))
    except Exception:
        pass

    # Salva WebP dentro do limite de 1MB
    img = canvas.convert("RGB")
    for quality in QUALITY_STEPS:
        img.save(str(dest), format="WEBP", quality=quality, method=6)
        if dest.stat().st_size <= MAX_SIZE_BYTES:
            break

    return {
        "path": str(dest),
        "size_kb": round(dest.stat().st_size / 1024, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera arte Instagram 1080x1350 WebP")
    parser.add_argument("--cover",        required=True)
    parser.add_argument("--slug",         required=True)
    parser.add_argument("--title",        required=True)
    parser.add_argument("--category",     default="Eventos")
    parser.add_argument("--output-dir",   default=".tmp")
    parser.add_argument("--art-title",    default="", help="Substitui --title como título da arte")
    parser.add_argument("--art-subtitle", default="", help="Linha de apoio da arte")
    parser.add_argument("--model",        default="", help="(ignorado — compatibilidade)")
    args = parser.parse_args()

    art_title = args.art_title if args.art_title else args.title
    result = generate_ig_image(
        args.cover, args.category, art_title, args.slug,
        args.output_dir, subtitle=args.art_subtitle,
    )
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
