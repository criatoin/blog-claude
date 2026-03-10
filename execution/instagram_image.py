"""
instagram_image.py — Gera arte para Instagram via composição Pillow.

Formato: 1080×1350px (4:5), WebP, <1MB

Camadas:
  1. Foto de capa — smart crop
  2. Gradiente rosa — overlay nos 45% inferiores (transparente → #FF3EB5 ~80%)
  3. Badge categoria — retângulo arredondado #C8E600, texto preto bold caps
  4. Título — texto branco bold, máx 3 linhas
  5. Logo — círculo +blog com máscara circular (remove fundo branco)

Uso:
    python execution/instagram_image.py \
        --cover .tmp/slug_cover.webp \
        --slug meu-post \
        --title "Título do evento" \
        --category "Diversão" \
        [--output-dir .tmp]

Saída JSON:
    {"path": ".tmp/slug_ig.webp", "size_kb": 420}
"""

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

IG_W, IG_H = 1080, 1350
MAX_SIZE_BYTES = 1 * 1024 * 1024
QUALITY_STEPS = [85, 75, 65, 55]

PROJECT_DIR = Path(__file__).parent.parent
FONT_PATH = str(PROJECT_DIR / "assets" / "fonts" / "Poppins-Bold.ttf")
LOGO_PATH = str(PROJECT_DIR / "Logo redondo +blog fundo rosa.png")

BADGE_COLOR = "#C8E600"
BADGE_TEXT_COLOR = "#1A1A1A"
GRADIENT_COLOR = (255, 62, 181)   # #FF3EB5 — rosa da marca
TITLE_COLOR = "white"

BADGE_FONT_SIZE = 30
TITLE_FONT_SIZE = 54
LOGO_SIZE = 110
MARGIN = 44


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


def _draw_gradient(img: Image.Image) -> Image.Image:
    """Gradiente rosa nos 45% inferiores."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    w, h = img.size
    start_y = int(h * 0.55)
    gradient_h = h - start_y
    r, g, b = GRADIENT_COLOR
    for y in range(gradient_h):
        alpha = int((y / gradient_h) * 204)
        draw.line([(0, start_y + y), (w, start_y + y)], fill=(r, g, b, alpha))
    base = img.convert("RGBA")
    composited = Image.alpha_composite(base, overlay)
    return composited.convert("RGB")


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()


def _draw_badge(draw: ImageDraw.Draw, category: str, x: int, y: int) -> int:
    """Desenha badge e retorna y da borda inferior."""
    font = _load_font(BADGE_FONT_SIZE)
    text = category.upper()
    bbox = font.getbbox(text)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    pad_x, pad_y = 22, 14
    rect_w = text_w + pad_x * 2
    rect_h = text_h + pad_y * 2
    draw.rounded_rectangle(
        [(x, y), (x + rect_w, y + rect_h)],
        radius=10,
        fill=BADGE_COLOR,
    )
    draw.text((x + pad_x, y + pad_y - bbox[1]), text, fill=BADGE_TEXT_COLOR, font=font)
    return y + rect_h


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        test = " ".join(current + [word])
        if font.getbbox(test)[2] > max_width and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines[:3]


def _draw_title(draw: ImageDraw.Draw, title: str, x: int, y: int, max_width: int) -> None:
    font = _load_font(TITLE_FONT_SIZE)
    lines = _wrap_text(title, font, max_width)
    line_height = TITLE_FONT_SIZE + 10
    for line in lines:
        draw.text((x, y), line, fill=TITLE_COLOR, font=font)
        y += line_height


def _paste_logo(img: Image.Image) -> Image.Image:
    """Cola logo circular no canto inferior direito com máscara."""
    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
    except Exception:
        return img
    logo = logo.resize((LOGO_SIZE, LOGO_SIZE), Image.LANCZOS)
    mask = Image.new("L", (LOGO_SIZE, LOGO_SIZE), 0)
    ImageDraw.Draw(mask).ellipse([(0, 0), (LOGO_SIZE, LOGO_SIZE)], fill=255)
    logo.putalpha(mask)
    x = img.width - LOGO_SIZE - MARGIN
    y = img.height - LOGO_SIZE - MARGIN
    img = img.convert("RGBA")
    img.paste(logo, (x, y), mask=logo)
    return img.convert("RGB")


def _compress_webp(img: Image.Image, dest: Path) -> None:
    for quality in QUALITY_STEPS:
        img.save(str(dest), format="WEBP", quality=quality, method=6)
        if dest.stat().st_size <= MAX_SIZE_BYTES:
            break


def generate_ig_image(
    cover_path: str,
    category: str,
    title: str,
    slug: str,
    output_dir: str = ".tmp",
) -> dict:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{slug}_ig.webp"

    # 1. Carrega e faz smart crop
    with Image.open(cover_path) as raw:
        img = _smart_crop(raw.convert("RGB"), IG_W, IG_H)

    # 2. Gradiente rosa
    img = _draw_gradient(img)

    # 3. Badge + título
    draw = ImageDraw.Draw(img)
    badge_x = MARGIN
    badge_y = int(IG_H * 0.62)
    badge_bottom = _draw_badge(draw, category, badge_x, badge_y)
    title_y = badge_bottom + 18
    _draw_title(draw, title, badge_x, title_y, IG_W - MARGIN * 2)

    # 4. Logo circular
    img = _paste_logo(img)

    # 5. Salva como WebP
    _compress_webp(img, dest)

    return {
        "path": str(dest),
        "size_kb": round(dest.stat().st_size / 1024, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera arte Instagram 1080x1350 WebP")
    parser.add_argument("--cover", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--category", default="Eventos")
    parser.add_argument("--output-dir", default=".tmp")
    # --model mantido por compatibilidade mas ignorado
    parser.add_argument("--model", default="", help="(ignorado — mantido para compatibilidade)")
    args = parser.parse_args()

    result = generate_ig_image(args.cover, args.category, args.title, args.slug, args.output_dir)
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
