"""Testa composição Pillow do instagram_image (balanced wrap + layout ancorado)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "execution"))

import pytest
from PIL import Image, ImageDraw

PROJECT_DIR = Path(__file__).parent.parent
FONT = PROJECT_DIR / "assets" / "fonts" / "Poppins-Bold.ttf"


@pytest.fixture
def cover(tmp_path):
    """Foto sintética 1600x900 — sem depender de asset externo."""
    p = tmp_path / "cover.jpg"
    img = Image.new("RGB", (1600, 900), (120, 60, 140))
    img.save(p, format="JPEG", quality=85)
    return str(p)


def test_fonte_existe():
    assert FONT.exists(), "Poppins-Bold.ttf não encontrada"


def test_title_fits_titulo_normal():
    from instagram_image import title_fits
    ok, motivo = title_fits("Americana recebe o 1º Sarau Ameriafro")
    assert ok, motivo


def test_title_fits_titulo_absurdo():
    from instagram_image import title_fits
    longo = "Inauguração extraordinariamente monumental da programação " * 4
    ok, motivo = title_fits(longo)
    assert not ok
    assert "encurte" in motivo


def test_balanced_wrap_equilibra_linhas():
    from instagram_image import _balanced_wrap, _load_font
    img = Image.new("RGBA", (1080, 1350))
    d = ImageDraw.Draw(img)
    font = _load_font(80, "black")
    linhas = _balanced_wrap("Festival de Jazz chega a Americana", font, 944, d)
    assert linhas is not None
    assert 1 <= len(linhas) <= 3
    # nenhuma linha estoura a largura máxima
    for l in linhas:
        assert d.textlength(l, font=font) <= 944


def test_generate_titulo_curto_nao_levanta_erro(cover, tmp_path):
    from instagram_image import generate_ig_image
    result = generate_ig_image(
        cover_path=cover, category="Cultura",
        title="Sarau Ameriafro",  # 2 palavras — antes levantava ValueError
        slug="t-curto", output_dir=str(tmp_path),
    )
    assert Path(result["path"]).exists()


def test_generate_titulo_longo_nao_trunca_em_6_palavras(cover, tmp_path):
    from instagram_image import generate_ig_image
    result = generate_ig_image(
        cover_path=cover, category="Música",
        title="Festival de Jazz gratuito no Parque Urbano",  # 7 palavras
        slug="t-longo", output_dir=str(tmp_path),
        subtitle="Sábado e domingo, a partir das 15h",
    )
    out = Path(result["path"])
    assert out.exists()
    img = Image.open(out)
    assert img.size == (1080, 1350)
    assert result.get("size_kb", 9999) < 1024
