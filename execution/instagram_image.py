"""
instagram_image.py — Gera arte para Instagram via composição Pillow.

Template global determinístico — estilo Ameriafro.

Formato: 1080×1350px (4:5), WebP, <1MB

Camadas (de baixo para cima):
  1. Foto full-bleed — smart crop preservando sujeitos principais
  2. Gradiente integrado — overlay longo e suave (transparente → magenta → roxo escuro)
  3. Badge categoria — amarelo/limão, texto preto bold, canto arredondado
  4. Título — texto branco bold, dominante, máx 3 linhas
  5. Linha de apoio — branca, menor que título, máx 2 linhas
  6. Logo rosa oficial centralizado no rodapé

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

# Gradiente: dois tons que se misturam sobre a foto
GRAD_COLOR_MID    = (160, 0, 120)   # magenta médio — entrada do gradiente
GRAD_COLOR_BOTTOM = (45,  0,  65)   # roxo muito escuro — rodapé

# ── Tipografia ─────────────────────────────────────────────────────────────────
BADGE_FONT_SIZE     = 32
TITLE_FONT_SIZE_MAX = 96
TITLE_FONT_SIZE_MIN = 60
SUPPORT_FONT_SIZE   = 38

# ── Layout global (template Ameriafro) ────────────────────────────────────────
# Todos os valores em pixels absolutos ou fração de IG_H.
TEXT_MARGIN          = 70   # margem esquerda/direita do bloco de texto

# Gradiente
GRAD_START_FRAC = 0.44      # começa em 44% da altura — transição bem cima
GRAD_FEATHER    = 0.12      # os primeiros 12% do gradiente ficam quase invisíveis

# Posição do badge (âncora superior do bloco de texto)
BADGE_TOP_Y = int(IG_H * 0.46)   # ~621px — início da zona de texto

# Espaçamentos internos do bloco
BADGE_TO_TITLE_GAP  = 38    # do bottom do badge até o top do título
TITLE_LINE_SPACING  = 1.15  # multiplicador de line-height sobre o tamanho da fonte
TITLE_TO_SUPPORT_GAP = 28   # do bottom do título até o top da linha de apoio
SUPPORT_LINE_SPACING = 1.20

# Logo
LOGO_HEIGHT         = 80    # altura real do conteúdo do logo (após bbox crop)
LOGO_BOTTOM_MARGIN  = 70    # margem entre bottom do logo e bottom do canvas
LOGO_Y = IG_H - LOGO_BOTTOM_MARGIN - LOGO_HEIGHT   # ~1200px

# Segurança: distância mínima entre bottom da linha de apoio e top do logo
MIN_SUPPORT_TO_LOGO_GAP = 70

# Se o bloco estoura para cima do gradiente, reduz fonte antes de comprimir layout
OVERFLOW_SHRINK_STEP = 4    # reduz em 4px por vez até TITLE_FONT_SIZE_MIN


def _smart_crop(img: Image.Image, w: int, h: int) -> Image.Image:
    """
    Redimensiona e corta a foto para preencher exatamente w×h pixels (full-bleed).
    Preserva sujeitos: crop vertical em 35% do topo (não centralizado),
    crop horizontal centralizado.
    Funciona para qualquer proporção de foto — vertical, quadrada ou horizontal.
    """
    src_w, src_h = img.size

    # Escala pelo eixo que deixa a imagem menor (cover, não contain)
    scale = max(w / src_w, h / src_h)
    new_w = int(src_w * scale)
    new_h = int(src_h * scale)
    resized = img.resize((new_w, new_h), Image.LANCZOS)

    # Corte horizontal: centro
    left = (new_w - w) // 2
    # Corte vertical: levemente acima do centro — preserva rostos/sujeitos
    top = max(0, int((new_h - h) * 0.35))

    return resized.crop((left, top, left + w, top + h))


def _draw_integrated_gradient(img: Image.Image) -> Image.Image:
    """
    Gradiente integrado estilo Ameriafro:
    - começa em GRAD_START_FRAC com alpha quase zero (feather)
    - cresce suavemente de forma não-linear
    - vai de magenta médio → roxo muito escuro no rodapé
    - nunca forma faixa visível — parece parte da foto
    """
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    w, h = img.size

    start_y    = int(h * GRAD_START_FRAC)
    feather_h  = int((h - start_y) * GRAD_FEATHER)  # zona de feather inicial
    gradient_h = h - start_y

    r_mid, g_mid, b_mid       = GRAD_COLOR_MID
    r_bot, g_bot, b_bot       = GRAD_COLOR_BOTTOM

    for y in range(gradient_h):
        t = y / gradient_h  # 0.0 → 1.0

        # Cor: interpola de GRAD_COLOR_MID para GRAD_COLOR_BOTTOM
        r = int(r_mid + (r_bot - r_mid) * t)
        g = int(g_mid + (g_bot - g_mid) * t)
        b = int(b_mid + (b_bot - b_mid) * t)

        # Alpha: feather suave na entrada, curva quadrática de crescimento
        if y < feather_h:
            # Zona de feather: 0 → ~40, muito suave
            raw_alpha = int(40 * (y / feather_h) ** 2)
        else:
            # Resto: cresce de 40 → 245 com curva levemente acelerada
            t_rest = (y - feather_h) / (gradient_h - feather_h)
            raw_alpha = int(40 + 205 * (t_rest ** 1.4))

        alpha = min(245, raw_alpha)
        draw.line([(0, start_y + y), (w, start_y + y)], fill=(r, g, b, alpha))

    base = img.convert("RGBA")
    return Image.alpha_composite(base, overlay).convert("RGB")


def _darken_if_bright(img: Image.Image, threshold: int = 170) -> Image.Image:
    """Escurece levemente fotos muito claras para garantir contraste com o texto."""
    from PIL import ImageEnhance, ImageStat
    stat = ImageStat.Stat(img.convert("RGB"))
    mean_brightness = sum(stat.mean[:3]) / 3
    if mean_brightness > threshold:
        return ImageEnhance.Brightness(img).enhance(0.75)
    return img


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()


def _load_logo() -> Image.Image | None:
    """Carrega logo, remove fundo branco, corta bbox vazia, retorna RGBA."""
    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
    except Exception:
        return None

    # Remove fundo branco/quase-branco
    data = logo.getdata()
    new_data = [
        (r, g, b, 0) if r > 230 and g > 230 and b > 230 else (r, g, b, a)
        for r, g, b, a in data
    ]
    logo.putdata(new_data)

    # Corta espaço vazio
    bbox = logo.getbbox()
    if bbox:
        logo = logo.crop(bbox)

    return logo


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


def _calculate_layout(
    title: str,
    subtitle: str,
    text_width: int,
) -> tuple[ImageFont.FreeTypeFont, list[str], list[str], int, int, int, int]:
    """
    Calcula layout completo do bloco de texto, evitando colisão com o logo.

    Retorna:
        (title_font, title_lines, support_lines,
         badge_y, title_y, support_y, logo_y)

    Lógica de colisão:
        Se support_bottom + MIN_SUPPORT_TO_LOGO_GAP > LOGO_Y:
            → reduz fonte do título (até TITLE_FONT_SIZE_MIN)
        Se ainda estoura → sobe badge_y até BADGE_TOP_Y - 60px no máximo
    """
    support_lines: list[str] = []
    support_h = 0

    if subtitle:
        support_font = _load_font(SUPPORT_FONT_SIZE)
        support_lines = _wrap_text(subtitle, support_font, text_width)[:2]
        support_line_h = int(SUPPORT_FONT_SIZE * SUPPORT_LINE_SPACING)
        support_h = len(support_lines) * support_line_h

    badge_font = _load_font(BADGE_FONT_SIZE)
    badge_sample = badge_font.getbbox("A")
    badge_h = (badge_sample[3] - badge_sample[1]) + 14 * 2  # pad_y=14

    # Tenta do maior para o menor tamanho de fonte
    for font_size in range(TITLE_FONT_SIZE_MAX, TITLE_FONT_SIZE_MIN - 1, -OVERFLOW_SHRINK_STEP):
        title_font = _load_font(font_size)
        title_lines = _wrap_text(title, title_font, text_width)[:3]
        line_h = int(font_size * TITLE_LINE_SPACING)
        title_h = len(title_lines) * line_h

        badge_y  = BADGE_TOP_Y
        title_y  = badge_y + badge_h + BADGE_TO_TITLE_GAP
        support_y = title_y + title_h + TITLE_TO_SUPPORT_GAP if subtitle else 0
        support_bottom = (support_y + support_h) if subtitle else (title_y + title_h)

        if support_bottom + MIN_SUPPORT_TO_LOGO_GAP <= LOGO_Y:
            break  # cabe com respiro adequado

    return title_font, title_lines, support_lines, badge_y, title_y, support_y, LOGO_Y


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


def _paste_logo(img: Image.Image, logo_y: int) -> Image.Image:
    """Cola logo centralizado horizontalmente em logo_y."""
    logo = _load_logo()
    if logo is None:
        return img
    orig_w, orig_h = logo.size
    new_w = int(orig_w * LOGO_HEIGHT / orig_h)
    logo = logo.resize((new_w, LOGO_HEIGHT), Image.LANCZOS)
    x = (IG_W - new_w) // 2
    base = img.convert("RGBA")
    base.paste(logo, (x, logo_y), mask=logo)
    return base.convert("RGB")


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

    text_width = IG_W - TEXT_MARGIN * 2

    # 1. Foto full-bleed (smart crop — mesma lógica para qualquer proporção)
    with Image.open(cover_path) as raw:
        img = _smart_crop(raw.convert("RGB"), IG_W, IG_H)

    # 2. Escurece se muito clara, depois aplica gradiente integrado
    img = _darken_if_bright(img)
    img = _draw_integrated_gradient(img)

    # 3. Calcula layout do bloco de texto com detecção de colisão
    title_font, title_lines, support_lines, badge_y, title_y, support_y, logo_y = (
        _calculate_layout(title, subtitle, text_width)
    )

    # 4. Logo
    img = _paste_logo(img, logo_y)

    # 5. Badge + texto
    draw = ImageDraw.Draw(img)
    _draw_badge(draw, category, TEXT_MARGIN, badge_y)

    line_h = int(title_font.size * TITLE_LINE_SPACING)
    y = title_y
    for line in title_lines:
        draw.text((TEXT_MARGIN, y), line, fill=TITLE_COLOR, font=title_font)
        y += line_h

    if support_lines:
        support_font = _load_font(SUPPORT_FONT_SIZE)
        support_line_h = int(SUPPORT_FONT_SIZE * SUPPORT_LINE_SPACING)
        y = support_y
        for line in support_lines:
            draw.text((TEXT_MARGIN, y), line, fill="white", font=support_font)
            y += support_line_h

    # 6. Salva WebP
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
