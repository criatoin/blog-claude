"""
instagram_image.py — Gera arte para Instagram via composição Pillow.

Formato: 1080×1350px (4:5), WebP, <1MB

Camadas (de baixo para cima):
  1. Foto de capa — smart crop
  2. Gradiente rosa — overlay nos 45% inferiores (transparente → #FF3EB5 ~80%)
  3. Logo flat centralizado na base
  4. Título — texto branco bold, máx 3 linhas (fonte ajusta automaticamente)
  5. Badge categoria — retângulo arredondado #C8E600, texto preto bold caps

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
LOGO_FLAT_PATH = str(PROJECT_DIR / "logos" / "Logo +blog roxo.png.png")

BADGE_COLOR = "#C8E600"
BADGE_TEXT_COLOR = "#1A1A1A"
GRADIENT_COLOR = (255, 62, 181)  # #FF3EB5 — rosa da marca
TITLE_COLOR = "white"

BADGE_FONT_SIZE = 30
TITLE_FONT_SIZE_MAX = 52
TITLE_FONT_SIZE_MIN = 28
MARGIN = 44

# Espaçamentos verticais (de baixo para cima)
BOTTOM_MARGIN = 60       # margem inferior da canvas
LOGO_HEIGHT = 75         # altura do logo flat
LOGO_GAP = 24            # gap entre logo e título
BADGE_TITLE_GAP = 16     # gap entre badge e título


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


def _remove_white_bg(img: Image.Image) -> Image.Image:
    """Converte fundo branco/quase-branco em transparente."""
    img = img.convert("RGBA")
    data = img.getdata()
    new_data = [
        (r, g, b, 0) if r > 230 and g > 230 and b > 230 else (r, g, b, a)
        for r, g, b, a in data
    ]
    img.putdata(new_data)
    return img


def _paste_logo_centered(img: Image.Image) -> tuple[Image.Image, int]:
    """
    Cola logo flat centralizado horizontalmente acima da margem inferior.
    Recorta o espaço em branco do PNG antes de redimensionar para que
    LOGO_HEIGHT corresponda à altura real do conteúdo do logo.
    Retorna (imagem, y_topo_do_logo) para calcular posição do texto acima.
    """
    logo_top_y = IG_H - BOTTOM_MARGIN - LOGO_HEIGHT
    try:
        logo = Image.open(LOGO_FLAT_PATH).convert("RGBA")
    except Exception:
        return img, logo_top_y

    logo = _remove_white_bg(logo)

    # Recorta o espaço vazio ao redor do conteúdo real do logo
    bbox = logo.getbbox()
    if bbox:
        logo = logo.crop(bbox)

    # Redimensiona pela altura mantendo proporção
    orig_w, orig_h = logo.size
    new_w = int(orig_w * LOGO_HEIGHT / orig_h)
    logo = logo.resize((new_w, LOGO_HEIGHT), Image.LANCZOS)

    x = (IG_W - new_w) // 2
    base = img.convert("RGBA")
    base.paste(logo, (x, logo_top_y), mask=logo)
    return base.convert("RGB"), logo_top_y


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
    return lines


def _fit_title_font(text: str, max_width: int) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Retorna a maior fonte que faz o título caber em até 3 linhas."""
    for size in range(TITLE_FONT_SIZE_MAX, TITLE_FONT_SIZE_MIN - 1, -2):
        font = _load_font(size)
        lines = _wrap_text(text, font, max_width)
        if len(lines) <= 3:
            return font, lines
    font = _load_font(TITLE_FONT_SIZE_MIN)
    lines = _wrap_text(text, font, max_width)
    return font, lines[:3]


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

    # 3. Logo flat centralizado na base
    img, logo_top_y = _paste_logo_centered(img)

    # 4. Badge + título ancorados acima do logo
    badge_font = _load_font(BADGE_FONT_SIZE)
    title_font, wrapped_lines = _fit_title_font(title, IG_W - MARGIN * 2)
    line_height = title_font.size + 10
    title_block_h = len(wrapped_lines) * line_height
    badge_sample = badge_font.getbbox("A")
    badge_h = (badge_sample[3] - badge_sample[1]) + 14 * 2

    title_y = logo_top_y - LOGO_GAP - title_block_h
    badge_y = title_y - BADGE_TITLE_GAP - badge_h

    draw = ImageDraw.Draw(img)
    _draw_badge(draw, category, MARGIN, badge_y)
    y = title_y
    for line in wrapped_lines:
        draw.text((MARGIN, y), line, fill=TITLE_COLOR, font=title_font)
        y += line_height

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
    parser.add_argument("--model", default="", help="(ignorado — mantido para compatibilidade)")
    args = parser.parse_args()

    result = generate_ig_image(args.cover, args.category, args.title, args.slug, args.output_dir)
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
