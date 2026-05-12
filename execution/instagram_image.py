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

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

load_dotenv()

IG_W, IG_H = 1080, 1350
MAX_SIZE_BYTES = 1 * 1024 * 1024
QUALITY_STEPS = [85, 75, 65, 55]

PROJECT_DIR = Path(__file__).parent.parent
FONT_PATH = str(PROJECT_DIR / "assets" / "fonts" / "Poppins-Bold.ttf")
LOGO_FLAT_PATH = str(PROJECT_DIR / "assets" / "logo" / "Logo +blog rosa.png")

BADGE_COLOR = "#C8E600"
BADGE_TEXT_COLOR = "#1A1A1A"
GRADIENT_TOP_COLOR    = (180, 0, 140)   # magenta escuro — início do gradiente
GRADIENT_BOTTOM_COLOR = (60, 0, 80)     # roxo quase preto — fim
GRADIENT_START_FRAC   = 0.42            # gradiente começa em 42% da altura
TITLE_COLOR = "white"

BADGE_FONT_SIZE      = 32
TITLE_FONT_SIZE_MAX  = 96
TITLE_FONT_SIZE_MIN  = 60
SUBTITLE_FONT_SIZE   = 38
MARGIN               = 70

# Espaçamentos verticais (de baixo para cima)
BOTTOM_MARGIN   = 50
LOGO_HEIGHT     = 80
LOGO_GAP        = 48   # respiro entre logo e título
BADGE_TITLE_GAP = 18
TITLE_SUB_GAP   = 14


def _build_photo_background(img: Image.Image, w: int, h: int) -> tuple[Image.Image, int]:
    """
    Constrói o fundo fotográfico para o canvas.
    Retorna (imagem_rgb, gradient_start_y).

    Estratégia por proporção da foto original:
    - Vertical ou quadrada (ratio ≤ 1.1): fit-and-crop central conservador.
      Gradiente começa em GRADIENT_START_FRAC do canvas.
    - Horizontal (ratio > 1.1): layout híbrido.
      Fundo borrado + foto principal posicionada preservando todos os sujeitos.
      Gradiente começa no terço inferior da foto principal (dentro dela).
    """
    from PIL import ImageFilter, ImageEnhance
    src_w, src_h = img.size
    src_ratio = src_w / src_h

    if src_ratio <= 1.1:
        # Foto vertical/quadrada: crop central conservador
        new_w = w
        new_h = int(src_h * w / src_w)
        if new_h < h:
            new_h = h
            new_w = int(src_w * h / src_h)
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - w) // 2
        top  = max(0, int((new_h - h) * 0.35))
        cropped = resized.crop((left, top, left + w, top + h))
        gradient_start_y = int(h * GRADIENT_START_FRAC)
        return cropped, gradient_start_y

    else:
        # Foto horizontal: layout híbrido fundo borrado + foto principal
        print(f"[instagram_image] Foto horizontal ({src_ratio:.2f}) — layout híbrido.", file=sys.stderr)

        # Fundo: zoom + blur forte + escurecimento
        scale_bg = max(w / src_w, h / src_h) * 1.05
        bg_w, bg_h = int(src_w * scale_bg), int(src_h * scale_bg)
        bg = img.resize((bg_w, bg_h), Image.LANCZOS)
        bx, by = (bg_w - w) // 2, (bg_h - h) // 2
        bg = bg.crop((bx, by, bx + w, by + h))
        bg = bg.filter(ImageFilter.GaussianBlur(radius=30))
        bg = ImageEnhance.Brightness(bg).enhance(0.40)

        # Foto principal: preenche 100% da altura do canvas (foto horizontal estica até o rodapé)
        # O fade na borda inferior dissolve a foto no fundo borrado, dando espaço visual para o texto
        max_photo_w = w
        max_photo_h = h  # altura total — sem gap roxo vazio abaixo da foto
        scale_photo = min(max_photo_w / src_w, max_photo_h / src_h)
        ph_w = int(src_w * scale_photo)
        ph_h = int(src_h * scale_photo)
        photo = img.resize((ph_w, ph_h), Image.LANCZOS)

        # Aplica máscara de fade na borda inferior da foto para fundir com o fundo borrado
        photo_rgba = photo.convert("RGBA")
        fade_zone = int(ph_h * 0.45)  # os últimos 45% da foto dissolvem gradualmente
        r_ch, g_ch, b_ch, a_ch = photo_rgba.split()
        import PIL.Image as _PILImage
        mask = _PILImage.new("L", (ph_w, ph_h), 255)
        mask_draw = ImageDraw.Draw(mask)
        for dy in range(fade_zone):
            alpha_val = int(255 * (1 - dy / fade_zone))
            mask_draw.line([(0, ph_h - fade_zone + dy), (ph_w, ph_h - fade_zone + dy)], fill=alpha_val)
        a_ch = _PILImage.composite(a_ch, _PILImage.new("L", (ph_w, ph_h), 0), mask)
        photo_rgba = _PILImage.merge("RGBA", (r_ch, g_ch, b_ch, a_ch))

        # Posiciona centralizada horizontalmente, alinhada ao topo
        canvas = bg.convert("RGBA")
        px = (w - ph_w) // 2
        py = 0
        canvas.paste(photo_rgba, (px, py), mask=photo_rgba)

        # Gradiente começa a 55% da altura — foto já está esmaecida nessa região
        gradient_start_y = int(h * 0.55)

        return canvas.convert("RGB"), gradient_start_y


def _draw_gradient(img: Image.Image, start_y: int | None = None) -> Image.Image:
    """Gradiente magenta→roxo escuro. start_y permite controle externo do ponto de início."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    w, h = img.size
    if start_y is None:
        start_y = int(h * GRADIENT_START_FRAC)
    gradient_h = h - start_y
    r1, g1, b1 = GRADIENT_TOP_COLOR
    r2, g2, b2 = GRADIENT_BOTTOM_COLOR
    for y in range(gradient_h):
        t = y / gradient_h
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        alpha = int(30 + t * 210)   # 30 → 240
        draw.line([(0, start_y + y), (w, start_y + y)], fill=(r, g, b, alpha))
    base = img.convert("RGBA")
    return Image.alpha_composite(base, overlay).convert("RGB")


def _darken_if_bright(img: Image.Image, threshold: int = 175) -> Image.Image:
    """Escurece levemente fotos muito claras para garantir contraste com o texto."""
    from PIL import ImageEnhance, ImageStat
    stat = ImageStat.Stat(img.convert("RGB"))
    mean_brightness = sum(stat.mean[:3]) / 3
    if mean_brightness > threshold:
        return ImageEnhance.Brightness(img).enhance(0.78)
    return img


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


def _paste_logo_at(img: Image.Image, logo_top_y: int) -> tuple[Image.Image, int]:
    """Cola logo flat centralizado horizontalmente em y explícito."""
    try:
        logo = Image.open(LOGO_FLAT_PATH).convert("RGBA")
    except Exception:
        return img, logo_top_y
    logo = _remove_white_bg(logo)
    bbox = logo.getbbox()
    if bbox:
        logo = logo.crop(bbox)
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
    subtitle: str = "",
) -> dict:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{slug}_ig.webp"

    # 1. Carrega e constrói fundo fotográfico
    with Image.open(cover_path) as raw:
        img, gradient_start_y = _build_photo_background(raw.convert("RGB"), IG_W, IG_H)

    # 2. Escurece se foto muito clara, depois aplica gradiente
    img = _darken_if_bright(img)
    img = _draw_gradient(img, start_y=gradient_start_y)

    # 4. Calcula alturas do bloco de texto e posiciona conjunto texto+logo
    badge_font = _load_font(BADGE_FONT_SIZE)
    subtitle_font = _load_font(SUBTITLE_FONT_SIZE)
    title_font, wrapped_lines = _fit_title_font(title, IG_W - MARGIN * 2)
    line_height = int(title_font.size * 1.15)
    title_block_h = len(wrapped_lines) * line_height

    subtitle_lines = _wrap_text(subtitle, subtitle_font, IG_W - MARGIN * 2)[:2] if subtitle else []
    subtitle_line_h = int(SUBTITLE_FONT_SIZE * 1.2)
    subtitle_block_h = len(subtitle_lines) * subtitle_line_h + (10 if subtitle_lines else 0)

    badge_sample = badge_font.getbbox("A")
    badge_h = (badge_sample[3] - badge_sample[1]) + 14 * 2

    # Ancora de baixo para cima: margem → logo → gap → texto → badge
    logo_top_y = IG_H - BOTTOM_MARGIN - LOGO_HEIGHT
    text_bottom = logo_top_y - LOGO_GAP
    title_y = text_bottom - title_block_h - subtitle_block_h
    badge_y = title_y - BADGE_TITLE_GAP - badge_h

    # Se o bloco ultrapassar o topo do gradiente, empurra para baixo até caber
    if badge_y < gradient_start_y:
        shift = gradient_start_y - badge_y
        badge_y += shift
        title_y += shift
        logo_top_y += shift

    # 3. Logo flat na posição calculada
    img, _ = _paste_logo_at(img, logo_top_y)

    draw = ImageDraw.Draw(img)
    _draw_badge(draw, category, MARGIN, badge_y)
    y = title_y
    for line in wrapped_lines:
        draw.text((MARGIN, y), line, fill=TITLE_COLOR, font=title_font)
        y += line_height

    if subtitle_lines:
        y += TITLE_SUB_GAP
        for line in subtitle_lines:
            draw.text((MARGIN, y), line, fill="white", font=subtitle_font)
            y += subtitle_line_h

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
    parser.add_argument("--art-title", default="", help="Título principal da arte (opcional, substitui --title)")
    parser.add_argument("--art-subtitle", default="", help="Linha de apoio da arte (opcional)")
    parser.add_argument("--model", default="", help="(ignorado — mantido para compatibilidade)")
    args = parser.parse_args()

    art_title = args.art_title if args.art_title else args.title
    result = generate_ig_image(args.cover, args.category, art_title, args.slug, args.output_dir, subtitle=args.art_subtitle)
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
