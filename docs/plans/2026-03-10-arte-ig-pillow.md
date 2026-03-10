# Arte IG Pillow + Link na Planilha — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Substituir a geração de arte IG via Gemini por composição determinística com Pillow, fiel ao template visual do +blog, e salvar URL pública (WordPress Media) na planilha em vez do caminho local.

**Architecture:** `instagram_image.py` é reescrito para compor a arte em camadas com Pillow (foto + gradiente rosa + badge lima + título branco + logo circular). Os pipelines `run_releases.py` e `run_pauta_produce.py` ganham uma chamada extra a `wp_publish.py upload-image` para obter a URL pública que vai para o Sheets.

**Tech Stack:** Pillow (já instalado), Poppins-Bold.ttf (a adicionar), `wp_publish.py upload-image` (já existe)

---

### Task 1: Adicionar fonte Poppins-Bold ao projeto

**Files:**
- Create: `assets/fonts/Poppins-Bold.ttf`

**Step 1: Baixar a fonte**

```bash
mkdir -p "assets/fonts"
curl -L "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Bold.ttf" \
     -o "assets/fonts/Poppins-Bold.ttf"
```

**Step 2: Verificar que o arquivo existe e tem tamanho razoável**

```bash
ls -lh assets/fonts/Poppins-Bold.ttf
# Esperado: arquivo com ~300KB
```

**Step 3: Commit**

```bash
git add assets/fonts/Poppins-Bold.ttf
git commit -m "feat: adiciona fonte Poppins-Bold para arte IG"
```

---

### Task 2: Reescrever `instagram_image.py` com composição Pillow

**Files:**
- Modify: `execution/instagram_image.py` (reescrever completamente)

**Contexto — template visual (baseado em `assets/instagram/6.jpg`):**
- Canvas: 1080 × 1350px
- Camada 1: foto de capa em smart crop
- Camada 2: gradiente rosa `#FF3EB5` nos 45% inferiores (opacidade 0 → 204/255)
- Camada 3: badge arredondado `#C8E600` com texto da categoria em preto bold caps
- Camada 4: título em branco bold abaixo do badge
- Camada 5: logo circular (PNG existente com máscara para remover fundo branco) no canto inferior direito

**Mapeamento categoria_id → nome do badge:**
```
23→Música, 22→Arte, 533→Audiovisual, 540→Literatura, 384→Educação
11→Diversão, 561→Carnaval, 13→Cultura, 19→Rolês, 10→Comida, 12→Eventos
```

**Step 1: Escrever teste**

Criar arquivo `tests/test_instagram_image.py`:

```python
"""Testa composição Pillow do instagram_image."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "execution"))

import pytest
from PIL import Image

PROJECT_DIR = Path(__file__).parent.parent
COVER = PROJECT_DIR / "assets" / "instagram" / "6.jpg"
LOGO = PROJECT_DIR / "Logo redondo +blog fundo rosa.png"
FONT = PROJECT_DIR / "assets" / "fonts" / "Poppins-Bold.ttf"


def test_assets_exist():
    assert COVER.exists(), "Cover model não encontrado"
    assert LOGO.exists(), "Logo não encontrado"
    assert FONT.exists(), "Fonte não encontrada"


def test_generate_ig_image(tmp_path):
    from instagram_image import generate_ig_image
    result = generate_ig_image(
        cover_path=str(COVER),
        category="Diversão",
        title="Pré-Carnaval em SBO rola nesse sábado no Mercadão da Cidade",
        slug="test-post",
        output_dir=str(tmp_path),
    )
    assert result.get("path"), "path não retornado"
    out = Path(result["path"])
    assert out.exists(), "Arquivo não criado"
    img = Image.open(out)
    assert img.size == (1080, 1350), f"Dimensões incorretas: {img.size}"
    assert result.get("size_kb", 9999) < 1024, "Arquivo maior que 1MB"


def test_generate_ig_image_long_title(tmp_path):
    from instagram_image import generate_ig_image
    result = generate_ig_image(
        cover_path=str(COVER),
        category="Música",
        title="Festival Internacional de Jazz chega a Americana com shows gratuitos no Parque Urbano neste fim de semana",
        slug="test-long-title",
        output_dir=str(tmp_path),
    )
    assert Path(result["path"]).exists()
```

**Step 2: Rodar teste para confirmar que falha**

```bash
cd "C:\Users\DANILLO\Desktop\LP's IA\+blog claude"
python -m pytest tests/test_instagram_image.py -v
# Esperado: FAIL — generate_ig_image com assinatura nova não existe ainda
```

**Step 3: Reescrever `execution/instagram_image.py`**

```python
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
    lines = []
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
    # Máscara circular para remover fundo branco
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
```

**Step 4: Rodar testes**

```bash
python -m pytest tests/test_instagram_image.py -v
# Esperado: PASS nos 3 testes
```

**Step 5: Inspecionar visualmente a imagem gerada**

```bash
python execution/instagram_image.py \
  --cover "assets/instagram/6.jpg" \
  --slug "teste-visual" \
  --title "Pré-Carnaval em SBO rola nesse sábado no Mercadão da Cidade, a partir das 16h, e é TUDO GRATUITO!" \
  --category "Diversão" \
  --output-dir ".tmp"
# Abre .tmp/teste-visual_ig.webp e verifica visualmente
```

**Step 6: Commit**

```bash
git add execution/instagram_image.py tests/test_instagram_image.py
git commit -m "feat: reescreve arte IG com composição Pillow fiel ao template +blog"
```

---

### Task 3: Atualizar `run_releases.py` — categoria no IG + upload WP + URL no Sheets

**Files:**
- Modify: `execution/run_releases.py`

**Contexto:** Três mudanças na função `processar_email`:
1. Adicionar mapeamento `wp_category_id → nome` para passar `--category` ao `instagram_image.py`
2. Após gerar `ig_path`, chamar `wp_publish.py upload-image` e capturar a URL pública
3. Salvar a URL (não o path local) no Sheets

**Step 1: Adicionar constante de mapeamento** logo após `VALID_CATEGORY_IDS` em `run_releases.py`:

```python
CATEGORY_NAMES = {
    23: "Música", 22: "Arte", 533: "Audiovisual", 540: "Literatura",
    384: "Educação", 11: "Diversão", 561: "Carnaval", 13: "Cultura",
    19: "Rolês", 10: "Comida", 12: "Eventos",
}
```

**Step 2: Atualizar bloco "Arte Instagram" dentro de `processar_email`**

Localizar (linhas ~397–409):
```python
    # 4. Arte Instagram
    ig_path = ""
    if cover_path and Path(cover_path).exists():
        ig_result = _run_json([
            str(SCRIPT_DIR / "instagram_image.py"),
            "--cover", cover_path,
            "--model", IG_MODEL,
            "--slug", slug,
            "--title", titulo,
            "--output-dir", OUTPUT_DIR,
        ])
        if ig_result:
            ig_path = ig_result.get("path", "")
```

Substituir por:
```python
    # 4. Arte Instagram
    ig_path = ""
    ig_url = ""
    if cover_path and Path(cover_path).exists():
        category_name = CATEGORY_NAMES.get(wp_category_id, "Eventos")
        ig_result = _run_json([
            str(SCRIPT_DIR / "instagram_image.py"),
            "--cover", cover_path,
            "--slug", slug,
            "--title", titulo,
            "--category", category_name,
            "--output-dir", OUTPUT_DIR,
        ])
        if ig_result:
            ig_path = ig_result.get("path", "")

    # Upload da arte IG para WP Media Library
    if ig_path and Path(ig_path).exists():
        upload_result = _run_json([
            str(SCRIPT_DIR / "wp_publish.py"), "upload-image",
            "--image-path", ig_path,
            "--title", f"{titulo} — Instagram",
        ])
        if upload_result:
            ig_url = upload_result.get("url", "")
```

**Step 3: Atualizar chamada ao Sheets** — trocar `"path_imagem": ig_path` por `"path_imagem": ig_url`

Localizar (dentro do `if ig_path:`):
```python
    if ig_path:
        _run_json([
            str(SCRIPT_DIR / "sheets_write.py"), "legenda-ig",
            "--data", json.dumps({
                "id_post": str(post_id),
                "titulo": titulo,
                "legenda": legenda,
                "hashtags": "",
                "status": "Pronta",
                "path_imagem": ig_path,
            }, ensure_ascii=False),
        ])
```

Substituir por:
```python
    if ig_url:
        _run_json([
            str(SCRIPT_DIR / "sheets_write.py"), "legenda-ig",
            "--data", json.dumps({
                "id_post": str(post_id),
                "titulo": titulo,
                "legenda": legenda,
                "hashtags": "",
                "status": "Pronta",
                "path_imagem": ig_url,
            }, ensure_ascii=False),
        ])
```

**Step 4: Atualizar args do `telegram_notify` na mesma função** — a chamada já usa `ig_path` para `--ig-image`, manter assim (é o path local para envio ao Telegram, não precisa mudar):

```python
    if ig_path:
        notify_args += ["--ig-image", ig_path, "--ig-caption", legenda]
```

Isso permanece igual — o Telegram recebe o arquivo local, o Sheets recebe a URL.

**Step 5: Verificar sintaxe**

```bash
python -c "import py_compile; py_compile.compile('execution/run_releases.py', doraise=True)"
# Esperado: sem saída (sem erros)
```

**Step 6: Commit**

```bash
git add execution/run_releases.py
git commit -m "feat: arte IG com categoria + upload WP + URL pública no Sheets (releases)"
```

---

### Task 4: Atualizar `run_pauta_produce.py` — mesmas mudanças

**Files:**
- Modify: `execution/run_pauta_produce.py`

**Step 1: Adicionar constante de mapeamento** logo após `VALID_CATEGORY_IDS`:

```python
CATEGORY_NAMES = {
    23: "Música", 22: "Arte", 533: "Audiovisual", 540: "Literatura",
    384: "Educação", 11: "Diversão", 561: "Carnaval", 13: "Cultura",
    19: "Rolês", 10: "Comida", 12: "Eventos",
}
```

**Step 2: Atualizar bloco "Arte Instagram"** (linhas ~287–298):

Localizar:
```python
    # 6. Arte Instagram
    ig_path = ""
    if cover_path and Path(cover_path).exists():
        ig_result = _run_json([
            str(SCRIPT_DIR / "instagram_image.py"),
            "--cover", cover_path,
            "--model", IG_MODEL,
            "--slug", slug,
            "--title", titulo,
            "--output-dir", OUTPUT_DIR,
        ])
        if ig_result:
            ig_path = ig_result.get("path", "")
```

Substituir por:
```python
    # 6. Arte Instagram
    ig_path = ""
    ig_url = ""
    if cover_path and Path(cover_path).exists():
        category_name = CATEGORY_NAMES.get(wp_category_id, "Eventos")
        ig_result = _run_json([
            str(SCRIPT_DIR / "instagram_image.py"),
            "--cover", cover_path,
            "--slug", slug,
            "--title", titulo,
            "--category", category_name,
            "--output-dir", OUTPUT_DIR,
        ])
        if ig_result:
            ig_path = ig_result.get("path", "")

    # Upload da arte IG para WP Media Library
    if ig_path and Path(ig_path).exists():
        upload_result = _run_json([
            str(SCRIPT_DIR / "wp_publish.py"), "upload-image",
            "--image-path", ig_path,
            "--title", f"{titulo} — Instagram",
        ])
        if upload_result:
            ig_url = upload_result.get("url", "")
```

**Step 3: Atualizar chamada ao Sheets** (bloco `if ig_path:` na linha ~325):

Localizar:
```python
    if ig_path:
        _run_json([
            str(SCRIPT_DIR / "sheets_write.py"), "legenda-ig",
            "--data", json.dumps({
                "id_post": str(post_id),
                "titulo": titulo,
                "legenda": legenda,
                "hashtags": "",
                "status": "Pronta",
                "path_imagem": ig_path,
            }, ensure_ascii=False),
        ])
```

Substituir por:
```python
    if ig_url:
        _run_json([
            str(SCRIPT_DIR / "sheets_write.py"), "legenda-ig",
            "--data", json.dumps({
                "id_post": str(post_id),
                "titulo": titulo,
                "legenda": legenda,
                "hashtags": "",
                "status": "Pronta",
                "path_imagem": ig_url,
            }, ensure_ascii=False),
        ])
```

**Step 4: Verificar sintaxe**

```bash
python -c "import py_compile; py_compile.compile('execution/run_pauta_produce.py', doraise=True)"
```

**Step 5: Commit**

```bash
git add execution/run_pauta_produce.py
git commit -m "feat: arte IG com categoria + upload WP + URL pública no Sheets (pautas)"
```

---

### Task 5: Atualizar diretiva `social-instagram.md`

**Files:**
- Modify: `directives/social-instagram.md`

**Step 1: Atualizar seção "Geração via instagram_image.py"**

Substituir o bloco bash de exemplo por:

```bash
python execution/instagram_image.py \
  --cover ".tmp/{slug}_cover.webp" \
  --slug "{slug}" \
  --title "{titulo}" \
  --category "{nome_da_categoria}"
```

Remover qualquer menção ao Gemini ou ao parâmetro `--model`.

Adicionar nota ao final da seção:
```
Após gerar a arte, fazer upload para WP Media Library:
    python execution/wp_publish.py upload-image \
      --image-path ".tmp/{slug}_ig.webp" \
      --title "{titulo} — Instagram"
A URL retornada é salva na coluna path_imagem da aba Legendas IG.
```

**Step 2: Commit**

```bash
git add directives/social-instagram.md
git commit -m "docs: atualiza diretiva IG com novo fluxo Pillow + upload WP"
```

---

### Task 6: Redeploy para produção

**Step 1: Push para main**

```bash
git push origin main
```

**Step 2: Trigger redeploy no Coolify**

```bash
curl -X POST \
  -H "Authorization: Bearer 4|KhjNZW4NJw39fm8eBKAeK21WMFGTnx4w92JsTunde8590ac2" \
  "https://serv2.criatoin.com.br/api/v1/deploy?uuid=ksko44gg48k0wsg04sosscsc&force=true"
```

**Step 3: Aguardar e verificar logs no Coolify**

Acessar `https://serv2.criatoin.com.br` e verificar que o container subiu sem erros.

---

## Resumo de arquivos alterados

| Arquivo | Ação |
|---------|------|
| `assets/fonts/Poppins-Bold.ttf` | Criar (download) |
| `execution/instagram_image.py` | Reescrever |
| `execution/run_releases.py` | Modificar (3 pontos) |
| `execution/run_pauta_produce.py` | Modificar (3 pontos) |
| `directives/social-instagram.md` | Atualizar |
| `tests/test_instagram_image.py` | Criar |
