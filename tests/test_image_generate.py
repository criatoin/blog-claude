"""Testa tri-state da vision e fim do placeholder em image_generate."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "execution"))


def test_validate_sem_chave_retorna_unavailable(monkeypatch, tmp_path):
    import image_generate
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    img = tmp_path / "x.jpg"
    img.write_bytes(b"fake")
    assert image_generate._validate_image(str(img), "titulo") == "unavailable"


def test_generate_sem_fontes_retorna_vazio_sem_placeholder(monkeypatch):
    import image_generate
    monkeypatch.setattr(image_generate, "_try_unsplash", lambda *a, **k: None)
    monkeypatch.setattr(image_generate, "_try_pexels", lambda *a, **k: None)
    monkeypatch.setattr(image_generate, "_try_gemini", lambda *a, **k: None)
    monkeypatch.setattr(image_generate, "_try_openai", lambda *a, **k: None)
    result = image_generate.generate_image("q", "slug", ".tmp", "titulo")
    assert result == {"path": "", "source": "none", "credit": "", "validated": False}
    assert not hasattr(image_generate, "_try_pil_placeholder"), "placeholder deve ser removido"
