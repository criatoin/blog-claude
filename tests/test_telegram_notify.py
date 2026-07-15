"""Testa card de imagem pendente e estado pending_images."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "execution"))


def test_send_image_pending_registra_estado(monkeypatch, tmp_path):
    import telegram_notify as tn

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    monkeypatch.setattr(tn, "PENDING_IMAGES_FILE", tmp_path / "pending_images.json")

    captured = {}

    def fake_api(method, poll_timeout=0, **kwargs):
        captured["method"] = method
        captured["kwargs"] = kwargs
        return {"ok": True, "result": {"message_id": 99}}

    monkeypatch.setattr(tn, "_api", fake_api)

    data = {
        "post_id": 42, "slug": "meu-post", "titulo": "Título",
        "category_name": "Cultura", "art_title": "Título arte",
        "art_subtitle": "apoio", "legenda_curta": "leg", "legenda_longa": "leg2",
        "edit_url": "https://x/edit", "summary": "resumo", "card_meta": {},
        "suggestion_path": "", "suggestion_credit": "",
    }
    result = tn.cmd_send_image_pending(data)
    assert result["ok"] is True

    state = json.loads((tmp_path / "pending_images.json").read_text(encoding="utf-8"))
    assert state["cards"]["99"]["post_id"] == 42
    assert state["awaiting"] is None

    # botões corretos no teclado
    kb = captured["kwargs"]["json"]["reply_markup"]["inline_keyboard"]
    datas = [b["callback_data"] for row in kb for b in row]
    assert "sendphoto:42" in datas
    assert "usethis:42" not in datas  # sem sugestão, botão "usar" não aparece
