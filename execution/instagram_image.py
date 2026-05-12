"""
instagram_image.py — Gera arte para Instagram via composição Pillow.

Template global determinístico — estilo Ameriafro.
Formato: 1080×1350px (4:5), WebP, <1MB

Composição em 4 camadas:
  1. Background full-canvas: foto cover+blur+escurecida (preenche o canvas inteiro)
  2. Foto principal: fit_width=1080, preserva grupo, fade inferior y=480→680
  3. Gradiente overlay: stops em y=0/500/700/1350, nunca retângulo sólido
  4. Texto e logo: badge~680, título~755, linha de apoio, logo no rodapé

Uso:
    python execution/instagram_image.py \
        --cover .tmp/slug_cover.webp \
        --slug meu-post \
        --title "Título do evento" \
        --category "Diversão" \
        [--art-subtitle "Linha de apoio curta"] \
        [--output-dir .tmp]

Saída JSON:
    {"path": ".tmp/slug_ig.webp", "size_kb": 420}
"""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

load_dotenv()

# ── Dimensões e limites ────────────────────────────────────────────────────────
IG_W, IG_H = 1080, 1350
MAX_SIZE_BYTES = 1 * 1024 * 1024
QUALITY_STEPS = [85, 75, 65, 55]

# ── Caminhos de assets ─────────────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).parent.parent
FONT_PATH = str(PROJECT_DIR / "assets" / "fonts" / "Poppins-Bold.ttf")
LOGO_PATH = str(PROJECT_DIR / "assets" / "logo" / "Logo +blog rosa.png")

# ── Paleta ─────────────────────────────────────────────────────────────────────
BADGE_COLOR      = "#C8E600"
BADGE_TEXT_COLOR = "#1A1A1A"
TITLE_COLOR      = "white"

# ── Tipografia ─────────────────────────────────────────────────────────────────
BADGE_FONT_SIZE     = 32
TITLE_FONT_SIZE_MAX = 96
TITLE_FONT_SIZE_MIN = 60
SUPPORT_FONT_SIZE   = 38

# ── Parâmetros do template ─────────────────────────────────────────────────────

# Camada 1 — background
BG_BLUR_RADIUS  = 18
BG_DARK_OPACITY = 0.20   # retângulo preto com 20% de opacidade

# Camada 2 — foto principal
PHOTO_FADE_START = 480   # px onde começa o fade inferior da foto
PHOTO_FADE_END   = 680   # px onde o fade termina (foto totalmente transparente)

# Camada 3 — gradiente overlay (stops em px)
GRAD_STOPS = [
    (0,    (0,   0,   0,   0  )),   # completamente transparente
    (500,  (0,   0,   0,   0  )),   # ainda transparente
    (700,  (180, 0,   120, 170)),   # magenta forte — igual à referência Ameriafro
    (1350, (80,  0,   60,  230)),   # magenta escuro/vinho profundo
]

# Camada 4 — texto
TEXT_MARGIN        = 70
BADGE_Y_DEFAULT    = 680
TITLE_Y_DEFAULT    = 755
BADGE_TO_TITLE_GAP = 32     # só usado se badge_h > (TITLE_Y_DEFAULT - BADGE_Y_DEFAULT - badge_h)
TITLE_LINE_SPACING = 1.15
TITLE_TO_SUP_GAP   = 24
SUPPORT_LINE_SPAC  = 1.20
BADGE_PAD_X        = 22
BADGE_PAD_Y        = 14

# Logo
LOGO_HEIGHT        = 80
LOGO_BOTTOM_MARGIN = 70
LOGO_Y = IG_H - LOGO_BOTTOM_MARGIN - LOGO_HEIGHT   # 1200px

# Colisão
MIN_SUP_TO_LOGO  = 80
FONT_SHRINK_STEP = 4


# ── Camada 1: background full-canvas ──────────────────────────────────────────

def _build_background(photo: Image.Image) -> Image.Image:
    """
    Redimensiona a foto para cobrir 1080×1350 (cover/crop central),
    aplica blur e escurece 20%.
    """
    from PIL import ImageFilter, ImageEnhance
    src_w, src_h = photo.size
    scale = max(IG_W / src_w, IG_H / src_h)
    new_w, new_h = int(src_w * scale), int(src_h * scale)
    resized = photo.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - IG_W) // 2
    top  = (new_h - IG_H) // 2
    bg = resized.crop((left, top, left + IG_W, top + IG_H))
    bg = bg.filter(ImageFilter.GaussianBlur(radius=BG_BLUR_RADIUS))
    # Escurecimento: overlay preto com 20% de opacidade
    dark = Image.new("RGBA", (IG_W, IG_H), (0, 0, 0, int(255 * BG_DARK_OPACITY)))
    bg_rgba = bg.convert("RGBA")
    bg_rgba = Image.alpha_composite(bg_rgba, dark)
    return bg_rgba.convert("RGB")


# ── Camada 2: foto principal com fade inferior ─────────────────────────────────

def _build_main_photo(photo: Image.Image) -> Image.Image:
    """
    Redimensiona a foto para fit_width=1080 (sem cortar laterais — preserva grupo completo).
    Aplica fade suave na borda inferior entre PHOTO_FADE_START e PHOTO_FADE_END.
    Retorna imagem RGBA pronta para alpha_composite.
    """
    src_w, src_h = photo.size
    scale = IG_W / src_w
    ph_w  = IG_W
    ph_h  = int(src_h * scale)
    resized = photo.resize((ph_w, ph_h), Image.LANCZOS)

    # Converte para RGBA para aplicar máscara de fade
    rgba = resized.convert("RGBA")
    r, g, b, a = rgba.split()

    # Máscara: 255 acima do fade_start, 0 abaixo do fade_end, gradiente no meio
    mask = Image.new("L", (ph_w, ph_h), 255)
    draw = ImageDraw.Draw(mask)

    fade_start = PHOTO_FADE_START
    fade_end   = min(PHOTO_FADE_END, ph_h)
    fade_range = max(1, fade_end - fade_start)

    for dy in range(fade_range):
        alpha_val = int(255 * (1 - dy / fade_range))
        y_px = fade_start + dy
        if y_px < ph_h:
            draw.line([(0, y_px), (ph_w, y_px)], fill=alpha_val)

    # Abaixo do fade_end: totalmente transparente
    if fade_end < ph_h:
        draw.rectangle([(0, fade_end), (ph_w, ph_h)], fill=0)

    a = Image.composite(a, Image.new("L", (ph_w, ph_h), 0), mask)
    return Image.merge("RGBA", (r, g, b, a))


# ── Camada 3: gradiente overlay com stops ─────────────────────────────────────

def _build_gradient_overlay() -> Image.Image:
    """
    Gradiente vertical com stops definidos em GRAD_STOPS.
    Interpola cor e alpha entre cada par de stops.
    Nunca usa retângulo sólido.
    """
    overlay = Image.new("RGBA", (IG_W, IG_H), (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)

    stops = GRAD_STOPS
    for i in range(len(stops) - 1):
        y0, (r0, g0, b0, a0) = stops[i]
        y1, (r1, g1, b1, a1) = stops[i + 1]
        seg_h = max(1, y1 - y0)
        for dy in range(seg_h):
            t = dy / seg_h
            r = int(r0 + (r1 - r0) * t)
            g = int(g0 + (g1 - g0) * t)
            b = int(b0 + (b1 - b0) * t)
            a = int(a0 + (a1 - a0) * t)
            y = y0 + dy
            if 0 <= y < IG_H:
                draw.line([(0, y), (IG_W, y)], fill=(r, g, b, a))

    return overlay


# ── Helpers de texto e logo ───────────────────────────────────────────────────

def _load_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()


def _load_logo() -> Image.Image | None:
    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
    except Exception:
        return None
    data = logo.getdata()
    logo.putdata([
        (r, g, b, 0) if r > 230 and g > 230 and b > 230 else (r, g, b, a)
        for r, g, b, a in data
    ])
    bbox = logo.getbbox()
    return logo.crop(bbox) if bbox else logo


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


def _calculate_layout(title: str, subtitle: str, text_width: int) -> dict:
    """
    Âncora superior: badge começa em BADGE_Y_DEFAULT (680px), título em TITLE_Y_DEFAULT (755px).
    Cresce para baixo: título → linha de apoio.
    Se a linha de apoio colidir com o logo (< MIN_SUP_TO_LOGO de distância),
    reduz a fonte do título até caber.
    """
    badge_font   = _load_font(BADGE_FONT_SIZE)
    badge_sample = badge_font.getbbox("A")
    badge_h      = (badge_sample[3] - badge_sample[1]) + BADGE_PAD_Y * 2

    support_font   = _load_font(SUPPORT_FONT_SIZE)
    support_line_h = int(SUPPORT_FONT_SIZE * SUPPORT_LINE_SPAC)

    if subtitle:
        support_lines = _wrap_text(subtitle, support_font, text_width)[:2]
        support_h = len(support_lines) * support_line_h
    else:
        support_lines = []
        support_h = 0

    badge_y = BADGE_Y_DEFAULT
    title_y = TITLE_Y_DEFAULT

    chosen = None
    for font_size in range(TITLE_FONT_SIZE_MAX, TITLE_FONT_SIZE_MIN - 1, -FONT_SHRINK_STEP):
        title_font  = _load_font(font_size)
        title_lines = _wrap_text(title, title_font, text_width)[:3]
        line_h      = int(font_size * TITLE_LINE_SPACING)
        title_h     = len(title_lines) * line_h

        support_y    = title_y + title_h + TITLE_TO_SUP_GAP if subtitle else 0
        block_bottom = (support_y + support_h) if subtitle else (title_y + title_h)

        if block_bottom + MIN_SUP_TO_LOGO <= LOGO_Y:
            chosen = (title_font, title_lines, line_h, support_y)
            break

    if chosen is None:
        font_size   = TITLE_FONT_SIZE_MIN
        title_font  = _load_font(font_size)
        title_lines = _wrap_text(title, title_font, text_width)[:3]
        line_h      = int(font_size * TITLE_LINE_SPACING)
        support_y   = title_y + len(title_lines) * line_h + TITLE_TO_SUP_GAP if subtitle else 0
        chosen      = (title_font, title_lines, line_h, support_y)

    title_font, title_lines, line_h, support_y = chosen

    return {
        "badge_y":        badge_y,
        "badge_h":        badge_h,
        "title_font":     title_font,
        "title_lines":    title_lines,
        "title_line_h":   line_h,
        "title_y":        title_y,
        "support_font":   support_font,
        "support_lines":  support_lines,
        "support_line_h": support_line_h,
        "support_y":      support_y,
        "logo_y":         LOGO_Y,
    }


def _draw_badge(draw: ImageDraw.Draw, category: str, x: int, y: int) -> None:
    font   = _load_font(BADGE_FONT_SIZE)
    text   = category.upper()
    bbox   = font.getbbox(text)
    rect_w = (bbox[2] - bbox[0]) + BADGE_PAD_X * 2
    rect_h = (bbox[3] - bbox[1]) + BADGE_PAD_Y * 2
    draw.rounded_rectangle([(x, y), (x + rect_w, y + rect_h)], radius=10, fill=BADGE_COLOR)
    draw.text((x + BADGE_PAD_X, y + BADGE_PAD_Y - bbox[1]), text,
              fill=BADGE_TEXT_COLOR, font=font)


def _paste_logo(canvas: Image.Image, logo_y: int) -> Image.Image:
    logo = _load_logo()
    if logo is None:
        return canvas
    orig_w, orig_h = logo.size
    new_w = int(orig_w * LOGO_HEIGHT / orig_h)
    logo  = logo.resize((new_w, LOGO_HEIGHT), Image.LANCZOS)
    x     = (IG_W - new_w) // 2
    base  = canvas.convert("RGBA")
    base.paste(logo, (x, logo_y), mask=logo)
    return base.convert("RGB")


def _compress_webp(img: Image.Image, dest: Path) -> None:
    for quality in QUALITY_STEPS:
        img.save(str(dest), format="WEBP", quality=quality, method=6)
        if dest.stat().st_size <= MAX_SIZE_BYTES:
            break


# ── Função principal ──────────────────────────────────────────────────────────

def generate_ig_image(
    cover_path: str,
    category: str,
    title: str,
    slug: str,
    output_dir: str = ".tmp",
    subtitle: str = "",
) -> dict:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{slug}_ig.webp"

    text_width = IG_W - TEXT_MARGIN * 2

    with Image.open(cover_path) as raw:
        photo = raw.convert("RGB")

    # CAMADA 1: background full-canvas (cover + blur + escurecimento)
    bg = _build_background(photo)
    canvas = bg.convert("RGBA")

    # CAMADA 2: foto principal com fade inferior (fit_width, sem cortar grupo)
    # Cola sobre o canvas RGBA — a foto pode ser menor que o canvas em altura
    main_photo = _build_main_photo(photo)
    ph_w, ph_h = main_photo.size
    layer2 = Image.new("RGBA", (IG_W, IG_H), (0, 0, 0, 0))
    layer2.paste(main_photo, (0, 0), mask=main_photo)
    canvas = Image.alpha_composite(canvas, layer2)

    # CAMADA 3: gradiente overlay com stops
    gradient = _build_gradient_overlay()
    canvas = Image.alpha_composite(canvas, gradient)

    # Converte para RGB antes de desenhar texto
    img = canvas.convert("RGB")

    # CAMADA 4: badge + título + linha de apoio + logo
    layout = _calculate_layout(title, subtitle, text_width)

    img = _paste_logo(img, layout["logo_y"])

    draw = ImageDraw.Draw(img)

    _draw_badge(draw, category, TEXT_MARGIN, layout["badge_y"])

    y = layout["title_y"]
    for line in layout["title_lines"]:
        draw.text((TEXT_MARGIN, y), line, fill=TITLE_COLOR, font=layout["title_font"])
        y += layout["title_line_h"]

    if layout["support_lines"]:
        y = layout["support_y"]
        for line in layout["support_lines"]:
            draw.text((TEXT_MARGIN, y), line, fill="white", font=layout["support_font"])
            y += layout["support_line_h"]

    _compress_webp(img, dest)

    return {
        "path": str(dest),
        "size_kb": round(dest.stat().st_size / 1024, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera arte Instagram 1080x1350 WebP")
    parser.add_argument("--cover",       required=True)
    parser.add_argument("--slug",        required=True)
    parser.add_argument("--title",       required=True)
    parser.add_argument("--category",    default="Eventos")
    parser.add_argument("--output-dir",  default=".tmp")
    parser.add_argument("--art-title",   default="", help="Substitui --title como título da arte")
    parser.add_argument("--art-subtitle",default="", help="Linha de apoio da arte")
    parser.add_argument("--model",       default="", help="(ignorado — compatibilidade)")
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
