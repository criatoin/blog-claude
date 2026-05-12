"""
instagram_image.py — Gera arte para Instagram via composição Pillow.

Template global determinístico — estilo Ameriafro.

Formato: 1080×1350px (4:5), WebP, <1MB

Estrutura visual (de cima para baixo):
  - Zona de foto (0–55% da altura): imagem preservada, sem texto
  - Zona de transição (45–70%): gradiente suave sobre a foto
  - Zona de texto (65–85%): badge + título + linha de apoio, sobre degradê sólido
  - Rodapé (85–100%): logo centralizado com respiro

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

# Gradiente: magenta → roxo muito escuro
GRAD_COLOR_TOP    = (160, 0, 110)   # magenta médio — entrada
GRAD_COLOR_BOTTOM = (35,  0,  55)   # roxo quase preto — rodapé

# ── Tipografia ─────────────────────────────────────────────────────────────────
BADGE_FONT_SIZE     = 32
TITLE_FONT_SIZE_MAX = 96
TITLE_FONT_SIZE_MIN = 60
SUPPORT_FONT_SIZE   = 38

# ── Template global (calibrado na referência Ameriafro) ────────────────────────

# Foto
PHOTO_CONTAIN_RATIO = 1.15   # fotos com ratio > isso recebem contain+blur lateral

# Gradiente — dois estágios
GRAD_FEATHER_START = 0.45    # começa invisível em 45% da altura
GRAD_STRONG_START  = 0.60    # fica sólido e escuro a partir de 60%
GRAD_MID_ALPHA     = 140     # alpha no ponto de transição
GRAD_BOTTOM_ALPHA  = 248     # alpha no rodapé

# Bloco de texto — safe area
TEXT_SAFE_MIN_Y   = 650      # badge nunca começa acima daqui
TEXT_MARGIN       = 70
BADGE_FONT_PAD_X  = 22
BADGE_FONT_PAD_Y  = 14

# Espaçamentos internos (badge → título → linha de apoio → logo)
BADGE_TO_TITLE_GAP   = 32
TITLE_LINE_SPACING   = 1.15
TITLE_TO_SUPPORT_GAP = 24
SUPPORT_LINE_SPACING = 1.20

# Logo
LOGO_HEIGHT         = 80
LOGO_BOTTOM_MARGIN  = 70
LOGO_Y = IG_H - LOGO_BOTTOM_MARGIN - LOGO_HEIGHT   # 1200px

# Distância mínima entre bottom da linha de apoio e top do logo
MIN_SUPPORT_TO_LOGO = 80

# Redução de fonte quando há colisão com o logo
FONT_SHRINK_STEP = 4


def _build_photo_background(img: Image.Image) -> Image.Image:
    """
    Constrói o fundo fotográfico full-bleed 1080×1350.

    Estratégia por proporção:
    - Vertical/quadrada (ratio ≤ PHOTO_CONTAIN_RATIO):
        scale-to-cover + crop conservador (35% do topo preserva cabeças).
    - Horizontal/grupo (ratio > PHOTO_CONTAIN_RATIO):
        contain com background blur — a foto principal aparece sem crop agressivo,
        lateral expandida com versão borrada+escurecida da mesma foto.
        Preserva o grupo de pessoas inteiro.
    """
    from PIL import ImageFilter, ImageEnhance
    w, h = IG_W, IG_H
    src_w, src_h = img.size
    ratio = src_w / src_h

    if ratio <= PHOTO_CONTAIN_RATIO:
        # Cover crop conservador
        scale = max(w / src_w, h / src_h)
        new_w, new_h = int(src_w * scale), int(src_h * scale)
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - w) // 2
        top  = max(0, int((new_h - h) * 0.35))
        return resized.crop((left, top, left + w, top + h))

    else:
        # Contain + blur lateral para fotos horizontais de grupo
        print(f"[instagram_image] Foto horizontal ({ratio:.2f}) — contain + blur.", file=sys.stderr)

        # Fundo: cover + blur forte + escurecimento agressivo
        scale_bg = max(w / src_w, h / src_h) * 1.08
        bg_w, bg_h = int(src_w * scale_bg), int(src_h * scale_bg)
        bg = img.resize((bg_w, bg_h), Image.LANCZOS)
        bx, by = (bg_w - w) // 2, (bg_h - h) // 2
        bg = bg.crop((bx, max(0, by), bx + w, max(0, by) + h))
        bg = bg.filter(ImageFilter.GaussianBlur(radius=35))
        bg = ImageEnhance.Brightness(bg).enhance(0.30)
        bg = bg.resize((w, h), Image.LANCZOS)  # garante tamanho exato

        # Foto principal: contain (scale pela menor dimensão) — sem cortar pessoas
        # Posiciona no topo centralizada horizontalmente
        scale_photo = min(w / src_w, h / src_h)
        ph_w = int(src_w * scale_photo)
        ph_h = int(src_h * scale_photo)
        photo = img.resize((ph_w, ph_h), Image.LANCZOS)

        # Cola foto principal no topo centralizada
        px = (w - ph_w) // 2
        py = 0
        canvas = bg.convert("RGBA")
        canvas.paste(photo.convert("RGBA"), (px, py))

        return canvas.convert("RGB")


def _draw_gradient(img: Image.Image) -> Image.Image:
    """
    Gradiente em dois estágios — estilo Ameriafro:

    Estágio 1 (GRAD_FEATHER_START → GRAD_STRONG_START):
        Alpha 0 → GRAD_MID_ALPHA de forma suave (feather).
        A foto ainda aparece, mas já começa a escurecer.

    Estágio 2 (GRAD_STRONG_START → fundo):
        Alpha GRAD_MID_ALPHA → GRAD_BOTTOM_ALPHA, rápido e sólido.
        Cria zona de leitura confiável para texto branco.

    Cor: magenta médio → roxo muito escuro (sem salto visível de cor).
    """
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    w, h = img.size

    y_feather = int(h * GRAD_FEATHER_START)   # onde começa o gradiente (~608px)
    y_strong  = int(h * GRAD_STRONG_START)    # onde fica sólido (~810px)

    r1, g1, b1 = GRAD_COLOR_TOP
    r2, g2, b2 = GRAD_COLOR_BOTTOM

    # Estágio 1: feather suave
    feather_h = y_strong - y_feather
    for i in range(feather_h):
        t = i / feather_h
        alpha = int(GRAD_MID_ALPHA * (t ** 1.5))  # curva suave
        cr = int(r1 + (r2 - r1) * t * 0.4)
        cg = int(g1 + (g2 - g1) * t * 0.4)
        cb = int(b1 + (b2 - b1) * t * 0.4)
        draw.line([(0, y_feather + i), (w, y_feather + i)], fill=(cr, cg, cb, alpha))

    # Estágio 2: sólido e escuro
    solid_h = h - y_strong
    for i in range(solid_h):
        t = i / solid_h
        alpha = int(GRAD_MID_ALPHA + (GRAD_BOTTOM_ALPHA - GRAD_MID_ALPHA) * (t ** 0.7))
        alpha = min(GRAD_BOTTOM_ALPHA, alpha)
        cr = int(r1 + (r2 - r1) * (0.4 + t * 0.6))
        cg = int(g1 + (g2 - g1) * (0.4 + t * 0.6))
        cb = int(b1 + (b2 - b1) * (0.4 + t * 0.6))
        draw.line([(0, y_strong + i), (w, y_strong + i)], fill=(cr, cg, cb, alpha))

    base = img.convert("RGBA")
    return Image.alpha_composite(base, overlay).convert("RGB")


def _darken_if_bright(img: Image.Image, threshold: int = 170) -> Image.Image:
    """Escurece levemente fotos muito claras."""
    from PIL import ImageEnhance, ImageStat
    stat = ImageStat.Stat(img.convert("RGB"))
    if sum(stat.mean[:3]) / 3 > threshold:
        return ImageEnhance.Brightness(img).enhance(0.75)
    return img


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()


def _load_logo() -> Image.Image | None:
    """Carrega logo, remove fundo branco, corta bbox."""
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


def _calculate_layout(title: str, subtitle: str, text_width: int):
    """
    Calcula posições de todos os elementos do bloco de texto.

    Âncora: de baixo para cima — logo fixo → linha de apoio → título → badge.
    O bloco de texto fica sempre compacto e grudado ao rodapé, como na referência.

    Se o badge ultrapassar TEXT_SAFE_MIN_Y (600px), reduz fonte do título.
    Garante que o badge nunca invada a área principal da foto.

    Retorna dict com todas as posições e fontes calculadas.
    """
    badge_font = _load_font(BADGE_FONT_SIZE)
    badge_sample = badge_font.getbbox("A")
    badge_h = (badge_sample[3] - badge_sample[1]) + BADGE_FONT_PAD_Y * 2

    support_font   = _load_font(SUPPORT_FONT_SIZE)
    support_line_h = int(SUPPORT_FONT_SIZE * SUPPORT_LINE_SPACING)

    if subtitle:
        support_lines = _wrap_text(subtitle, support_font, text_width)[:2]
        support_h = len(support_lines) * support_line_h
    else:
        support_lines = []
        support_h = 0

    # Âncora inferior: logo_top → acima com MIN_SUPPORT_TO_LOGO de respiro
    anchor_bottom = LOGO_Y - MIN_SUPPORT_TO_LOGO  # bottom do bloco de texto

    # Tenta do maior ao menor tamanho de fonte
    chosen = None
    for font_size in range(TITLE_FONT_SIZE_MAX, TITLE_FONT_SIZE_MIN - 1, -FONT_SHRINK_STEP):
        title_font  = _load_font(font_size)
        title_lines = _wrap_text(title, title_font, text_width)[:3]
        line_h      = int(font_size * TITLE_LINE_SPACING)
        title_h     = len(title_lines) * line_h

        # Calcula de baixo para cima
        support_bottom = anchor_bottom
        support_y      = support_bottom - support_h if subtitle else 0
        title_bottom   = (support_y - TITLE_TO_SUPPORT_GAP) if subtitle else support_bottom
        title_y        = title_bottom - title_h
        badge_y        = title_y - BADGE_TO_TITLE_GAP - badge_h

        if badge_y >= TEXT_SAFE_MIN_Y:
            chosen = (title_font, title_lines, line_h, badge_y, title_y, support_y)
            break

    if chosen is None:
        # Fonte mínima — pode subir levemente acima de TEXT_SAFE_MIN_Y se não houver opção
        font_size   = TITLE_FONT_SIZE_MIN
        title_font  = _load_font(font_size)
        title_lines = _wrap_text(title, title_font, text_width)[:3]
        line_h      = int(font_size * TITLE_LINE_SPACING)
        title_h     = len(title_lines) * line_h
        support_bottom = anchor_bottom
        support_y      = support_bottom - support_h if subtitle else 0
        title_bottom   = (support_y - TITLE_TO_SUPPORT_GAP) if subtitle else support_bottom
        title_y        = title_bottom - title_h
        badge_y        = title_y - BADGE_TO_TITLE_GAP - badge_h
        chosen = (title_font, title_lines, line_h, badge_y, title_y, support_y)

    title_font, title_lines, line_h, badge_y, title_y, support_y = chosen

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
    font = _load_font(BADGE_FONT_SIZE)
    text = category.upper()
    bbox = font.getbbox(text)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    rect_w = text_w + BADGE_FONT_PAD_X * 2
    rect_h = text_h + BADGE_FONT_PAD_Y * 2
    draw.rounded_rectangle([(x, y), (x + rect_w, y + rect_h)], radius=10, fill=BADGE_COLOR)
    draw.text((x + BADGE_FONT_PAD_X, y + BADGE_FONT_PAD_Y - bbox[1]), text,
              fill=BADGE_TEXT_COLOR, font=font)


def _paste_logo(img: Image.Image, logo_y: int) -> Image.Image:
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

    # 1. Foto de fundo (preserva grupo, sem zoom agressivo para horizontais)
    with Image.open(cover_path) as raw:
        img = _build_photo_background(raw.convert("RGB"))

    # 2. Escurece foto muito clara
    img = _darken_if_bright(img)

    # 3. Gradiente em dois estágios: feather suave + zona sólida de leitura
    img = _draw_gradient(img)

    # 4. Calcula layout do bloco de texto
    layout = _calculate_layout(title, subtitle, text_width)

    # 5. Logo no rodapé
    img = _paste_logo(img, layout["logo_y"])

    # 6. Badge + título + linha de apoio
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

    # 7. Salva WebP
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
    parser.add_argument("--art-title", default="", help="Substitui --title como título da arte")
    parser.add_argument("--art-subtitle", default="", help="Linha de apoio da arte")
    parser.add_argument("--model", default="", help="(ignorado — compatibilidade)")
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
