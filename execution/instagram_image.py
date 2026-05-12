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
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

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

    # ── CAMADA 1: Blur cobre TODO o canvas ────────────────────────────────────
    src = Image.open(cover_path).convert("RGBA")

    # cover crop manual: max(scale_x, scale_y) garante que não sobra área vazia
    scale = max(W / src.width, H / src.height)
    bw = int(src.width * scale)
    bh = int(src.height * scale)
    bg = src.resize((bw, bh), Image.LANCZOS)
    left = (bw - W) // 2
    top  = max(0, (bh - H) // 3)  # ancora no terço superior
    bg = bg.crop((left, top, left + W, top + H))
    bg = bg.filter(ImageFilter.GaussianBlur(radius=22))
    dark = Image.new("RGBA", (W, H), (0, 0, 0, 90))
    bg = Image.alpha_composite(bg, dark)
    canvas = bg.copy()  # canvas COMEÇA como blur — nunca Image.new vazio

    # ── CAMADA 2: Foto principal proporcional (fit_width, sem corte vertical) ─
    photo = src.copy()
    scale2 = W / photo.width
    pw = W
    ph = int(photo.height * scale2)
    photo = photo.resize((pw, ph), Image.LANCZOS)
    photo = ImageEnhance.Contrast(photo).enhance(1.15)
    photo = ImageEnhance.Color(photo).enhance(1.20)
    photo = ImageEnhance.Sharpness(photo).enhance(1.10)
    canvas.alpha_composite(photo, (0, 0))  # ancora no topo

    # ── CAMADA 3: Degradê overlay (nunca sólido, alpha máx 210) ───────────────
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dg   = ImageDraw.Draw(grad)
    S, M, E = 580, 810, H

    for y in range(H):
        if y < S:
            dg.line([(0, y), (W, y)], fill=(0, 0, 0, 0))
        elif y < M:
            p = (y - S) / (M - S)
            r = int(230 * p)
            b = int(126 * p)
            a = int(185 * p)
            dg.line([(0, y), (W, y)], fill=(r, 0, b, a))
        else:
            p = min(1.0, (y - M) / (E - M))
            r = int(230 - (230 - 59) * p)
            b = int(126 + (95 - 126) * p)
            a = int(185 + (210 - 185) * p)
            dg.line([(0, y), (W, y)], fill=(r, 0, b, a))

    canvas.alpha_composite(grad)

    # ── CAMADA 4: Textos ───────────────────────────────────────────────────────
    d = ImageDraw.Draw(canvas)

    # Tag de categoria
    ft     = _load_font(28, "bold")
    cat_up = category.upper()
    bb     = d.textbbox((0, 0), cat_up, font=ft)
    tw     = bb[2] - bb[0]
    th     = bb[3] - bb[1]
    TX, TY, PW, PH = 68, 720, 32, 14  # TAG_Y=720 (mais baixo que 660)
    rect = [TX, TY, TX + tw + PW * 2, TY + th + PH * 2]
    d.rounded_rectangle(rect, radius=8, fill=(221, 230, 0))
    d.text((TX + PW, TY + PH), cat_up, font=ft, fill=(0, 0, 0))
    tag_bottom = rect[3]

    # Título — grupos de 2 palavras por linha, tamanho máximo que cabe em 940px
    words  = title.split()
    linhas = [" ".join(words[i:i+2]) for i in range(0, len(words), 2)]

    tamanho = 105
    fonte_ok = None
    while tamanho >= 56:
        fti = _load_font(tamanho, "black")
        linha_mais_longa = max(d.textlength(l, font=fti) for l in linhas)
        if linha_mais_longa <= 940:
            fonte_ok = fti
            break
        tamanho -= 2

    if fonte_ok is None:
        # Fallback: 1 palavra por linha com fonte mínima
        fonte_ok = _load_font(56, "black")
        linhas = words

    ty = tag_bottom + 22
    for linha in linhas:
        d.text((68, ty), linha, font=fonte_ok, fill=(255, 255, 255))
        ty += int(fonte_ok.size * 1.08)

    # Linha de apoio — sem truncagem, quebra automática em 940px
    if subtitle:
        fa = _load_font(38, "regular")
        ay = ty + 32
        for linha in _quebrar_linhas(subtitle, fa, 940, d):
            d.text((68, ay), linha, font=fa, fill=(255, 255, 255))
            ay += int(fa.size * 1.35)

    # ── Logo no rodapé ─────────────────────────────────────────────────────────
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
        LW   = 300
        LH   = int(logo.height * LW / logo.width)
        logo = logo.resize((LW, LH), Image.LANCZOS)
        LX   = (W - LW) // 2
        LY   = H - LH - 58
        canvas.alpha_composite(logo, (LX, LY))
    except Exception:
        pass

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
