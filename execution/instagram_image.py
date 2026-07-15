"""
instagram_image.py — Gera arte para Instagram via composição Pillow.

Template +blog — padrão Ameriafro — 4 camadas:
  1. Blur full-bleed (cobre todo o canvas) + escurecimento
  2. Foto principal proporcional ancorada no topo (fit_width)
  3. Degradê overlay magenta→roxo (alpha máx 210, nunca 255)
  4. Textos: tag categoria + título + linha de apoio + logo

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
import os
import sys
from itertools import combinations
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

load_dotenv()

IG_W, IG_H = 1080, 1350
MAX_SIZE_BYTES = 1 * 1024 * 1024
QUALITY_STEPS  = [85, 75, 65, 55]

PROJECT_DIR = Path(__file__).parent.parent
LOGO_PATH   = str(PROJECT_DIR / "assets" / "logo" / "Logo +blog rosa.png")

_FONT_SEARCH_DIRS = [
    str(PROJECT_DIR / "assets" / "fonts"),
    "/usr/share/fonts",
    "/usr/share/fonts/truetype",
    "/usr/share/fonts/truetype/dejavu",
    "/System/Library/Fonts",
]
_FONT_CANDIDATES = {
    "black":   ["Poppins-Bold.ttf", "DejaVuSans-Bold.ttf", "arialbd.ttf"],
    "bold":    ["Poppins-Bold.ttf", "DejaVuSans-Bold.ttf", "arialbd.ttf"],
    "regular": ["Poppins-Bold.ttf", "DejaVuSans.ttf", "arial.ttf"],
}


def _load_font(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    for name in _FONT_CANDIDATES.get(weight, _FONT_CANDIDATES["regular"]):
        for base in _FONT_SEARCH_DIRS:
            path = os.path.join(base, name)
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _quebrar_linhas(texto: str, font: ImageFont.FreeTypeFont, max_w: int, draw: ImageDraw.ImageDraw) -> list[str]:
    words = texto.split()
    lines: list[str] = []
    line = ""
    for w in words:
        test = (line + " " + w).strip()
        if draw.textlength(test, font=font) <= max_w:
            line = test
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


TITLE_MAX_W  = 944
TITLE_SIZE_MAX = 92
TITLE_SIZE_MIN = 60
TITLE_MAX_LINES = 3


def _particao_equilibrada(words: list[str], n: int, font, max_w: int, draw) -> list[str] | None:
    """Divide words em n linhas contíguas minimizando a linha mais larga."""
    if n == 1:
        linha = " ".join(words)
        return [linha] if draw.textlength(linha, font=font) <= max_w else None
    if len(words) < n:
        return None
    melhor, melhor_max = None, None
    for cortes in combinations(range(1, len(words)), n - 1):
        partes, inicio = [], 0
        for c in list(cortes) + [len(words)]:
            partes.append(" ".join(words[inicio:c]))
            inicio = c
        larguras = [draw.textlength(p, font=font) for p in partes]
        if max(larguras) > max_w:
            continue
        if melhor_max is None or max(larguras) < melhor_max:
            melhor, melhor_max = partes, max(larguras)
    return melhor


def _balanced_wrap(texto: str, font, max_w: int, draw, max_lines: int = TITLE_MAX_LINES) -> list[str] | None:
    """Menor nº de linhas em que o texto cabe, com larguras equilibradas. None se não couber."""
    words = texto.split()
    if not words:
        return None
    for n in range(1, max_lines + 1):
        linhas = _particao_equilibrada(words, n, font, max_w, draw)
        if linhas is not None:
            return linhas
    return None


def compor_titulo(title: str, draw, max_w: int = TITLE_MAX_W,
                  size_max: int = TITLE_SIZE_MAX, size_min: int = TITLE_SIZE_MIN):
    """Retorna (linhas, fonte) na maior fonte que caiba, ou (None, None)."""
    for size in range(size_max, size_min - 1, -2):
        font = _load_font(size, "black")
        linhas = _balanced_wrap(title, font, max_w, draw)
        if linhas is not None:
            return linhas, font
    return None, None


def title_fits(title: str) -> tuple[bool, str]:
    """Preflight: o título renderiza em <=3 linhas com fonte >=60pt?"""
    img = Image.new("RGBA", (IG_W, IG_H))
    d = ImageDraw.Draw(img)
    linhas, _ = compor_titulo(title, d)
    if linhas is None:
        return False, (
            f"título não cabe em {TITLE_MAX_LINES} linhas com fonte mínima "
            f"{TITLE_SIZE_MIN}pt — encurte para até ~70 caracteres"
        )
    return True, ""


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

    # ── CAMADA 1: Fundo escuro sólido cobre TODO o canvas ────────────────────
    # Fundo preto/escuro uniforme: garante que a zona abaixo da foto (quando
    # a foto é horizontal e não cobre o canvas inteiro) fique escura e
    # compatível com o degradê magenta/roxo — sem mancha de blur cinza.
    src = Image.open(cover_path).convert("RGBA")
    canvas = Image.new("RGBA", (W, H), (10, 0, 15, 255))  # roxo-preto escuro

    # ── CAMADA 2: Foto principal — fit_width + fade fixo nos últimos 200px ──
    # fit_width: preserva todas as pessoas sem corte lateral
    # fade fixo (200px): suaviza borda inferior sem expor grande área de blur
    photo = src.copy()
    scale2 = W / photo.width
    pw = W
    ph = int(photo.height * scale2)
    photo = photo.resize((pw, ph), Image.LANCZOS)
    photo = ImageEnhance.Contrast(photo).enhance(1.15)
    photo = ImageEnhance.Color(photo).enhance(1.20)
    photo = ImageEnhance.Sharpness(photo).enhance(1.10)

    # Fade nos últimos 200px da foto (pixels fixos, independente da altura)
    FADE_PX = 200
    fade_start = max(0, ph - FADE_PX)
    mask = Image.new("L", (pw, ph), 255)
    draw_mask = ImageDraw.Draw(mask)
    for y in range(fade_start, ph):
        alpha_val = int(255 * (1 - (y - fade_start) / FADE_PX))
        draw_mask.line([(0, y), (pw, y)], fill=alpha_val)
    photo.putalpha(mask)

    canvas.alpha_composite(photo, (0, 0))

    # ── CAMADA 3: Degradê overlay (nunca sólido, alpha máx 210) ───────────────
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dg   = ImageDraw.Draw(grad)
    S, M, E = 420, 850, H  # transição muito mais longa e suave

    for y in range(H):
        if y < S:
            dg.line([(0, y), (W, y)], fill=(0, 0, 0, 0))
        elif y < M:
            p = (y - S) / (M - S)
            p_ease = p * p  # ease-in: início muito suave
            r = int(230 * p_ease)
            b = int(126 * p_ease)
            a = int(175 * p_ease)
            dg.line([(0, y), (W, y)], fill=(r, 0, b, a))
        else:
            p = min(1.0, (y - M) / (E - M))
            r = int(230 - (230 - 59) * p)
            b = int(126 + (95  - 126) * p)
            a = int(175 + (210 - 175) * p)
            dg.line([(0, y), (W, y)], fill=(r, 0, b, a))

    canvas.alpha_composite(grad)

    # ── CAMADA 4: Textos ───────────────────────────────────────────────────────
    d = ImageDraw.Draw(canvas)

    # ── Logo (calculado ANTES dos textos — âncora do layout) ─────────────────
    logo_img, logo_pos = None, None
    logo_top = H - 58 - 90  # fallback se logo falhar: reserva ~90px
    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
        pixels = list(logo.getdata())
        logo.putdata([
            (r, g, b, 0) if r > 230 and g > 230 and b > 230 else (r, g, b, a)
            for r, g, b, a in pixels
        ])
        bbox = logo.getbbox()
        if bbox:
            logo = logo.crop(bbox)
        LW = 240
        LH = int(logo.height * LW / logo.width)
        logo_img = logo.resize((LW, LH), Image.LANCZOS)
        logo_pos = ((W - LW) // 2, H - LH - 58)
        logo_top = logo_pos[1]
    except Exception as e:
        print(f"[instagram_image] aviso: logo não colado — {e}", file=sys.stderr)

    # ── Título: balanced wrap com autosize; fallback duro se não couber ──────
    linhas, fonte_ok = compor_titulo(title, d)
    if linhas is None:
        # Último recurso determinístico: fonte mínima, quebra gulosa, 3 linhas + "…"
        fonte_ok = _load_font(TITLE_SIZE_MIN, "black")
        linhas = _quebrar_linhas(title, fonte_ok, TITLE_MAX_W, d)[:TITLE_MAX_LINES]
        if linhas:
            linhas[-1] = linhas[-1].rstrip() + "…"
        print(f"[instagram_image] aviso: título não coube — truncado com reticências.",
              file=sys.stderr)

    # ── Linha de apoio (medida antes de posicionar o bloco) ──────────────────
    fa = _load_font(38, "regular")
    sub_linhas = _quebrar_linhas(subtitle, fa, 940, d) if subtitle else []

    # ── Alturas do bloco de texto (badge + título + apoio) ───────────────────
    ft = _load_font(28, "bold")
    cat_up = category.upper()
    bb = d.textbbox((0, 0), cat_up, font=ft)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    PW, PH = 32, 14  # padding interno do badge
    badge_h = th + PH * 2
    titulo_h = int(fonte_ok.size * 1.08) * len(linhas)
    apoio_h = (32 + int(fa.size * 1.35) * len(sub_linhas)) if sub_linhas else 0
    bloco_h = badge_h + 22 + titulo_h + apoio_h

    # ── Posiciona o bloco ancorado acima do logo, com respiro de 40px ────────
    y0 = logo_top - 40 - bloco_h

    # Badge
    TX = 68
    rect = [TX, y0, TX + tw + PW * 2, y0 + badge_h]
    d.rounded_rectangle(rect, radius=8, fill=(221, 230, 0))
    d.text((TX + PW, y0 + PH), cat_up, font=ft, fill=(0, 0, 0))

    # Título
    ty = rect[3] + 22
    for linha in linhas:
        d.text((68, ty), linha, font=fonte_ok, fill=(255, 255, 255))
        ty += int(fonte_ok.size * 1.08)

    # Linha de apoio
    if sub_linhas:
        ay = ty + 32
        for linha in sub_linhas:
            d.text((68, ay), linha, font=fa, fill=(255, 255, 255))
            ay += int(fa.size * 1.35)

    # Logo por último (por cima do degradê)
    if logo_img is not None:
        canvas.alpha_composite(logo_img, logo_pos)

    # ── Salva WebP dentro do limite de 1MB ────────────────────────────────────
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
    parser.add_argument("--cover",         required=True)
    parser.add_argument("--slug",          required=True)
    parser.add_argument("--title",         required=True)
    parser.add_argument("--category",      default="Eventos")
    parser.add_argument("--output-dir",    default=".tmp")
    parser.add_argument("--art-title",     default="", help="Substitui --title como título da arte")
    parser.add_argument("--art-subtitle",  default="", help="Linha de apoio da arte")
    parser.add_argument("--model",         default="", help="(ignorado — compatibilidade)")
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
