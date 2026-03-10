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
