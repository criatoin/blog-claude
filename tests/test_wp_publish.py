"""Testa find_post e set_featured com API mockada."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "execution"))


def _setup_env(monkeypatch):
    monkeypatch.setenv("WP_URL", "https://exemplo.com")
    monkeypatch.setenv("WP_USER", "u")
    monkeypatch.setenv("WP_APP_PASSWORD", "p")


class FakeResp:
    def __init__(self, payload):
        self._payload = payload
        self.ok = True
        self.status_code = 200

    def json(self):
        return self._payload


def test_find_post_por_slug_existente(monkeypatch):
    _setup_env(monkeypatch)
    import wp_publish

    def fake_get(url, params=None, auth=None):
        assert params["slug"] == "meu-post"
        return FakeResp([{"id": 42, "status": "draft"}])

    monkeypatch.setattr(wp_publish.requests, "get", fake_get)
    result = wp_publish.find_post(slug="meu-post")
    assert result == {"exists": True, "post_id": 42, "status": "draft"}


def test_find_post_inexistente(monkeypatch):
    _setup_env(monkeypatch)
    import wp_publish

    monkeypatch.setattr(wp_publish.requests, "get",
                        lambda url, params=None, auth=None: FakeResp([]))
    result = wp_publish.find_post(slug="nao-existe")
    assert result == {"exists": False, "post_id": None, "status": ""}


def test_set_featured(monkeypatch, tmp_path):
    _setup_env(monkeypatch)
    import wp_publish

    img = tmp_path / "a.jpg"
    img.write_bytes(b"fake")

    monkeypatch.setattr(wp_publish, "upload_image",
                        lambda p, title="": {"media_id": 7, "url": "https://exemplo.com/a.jpg"})

    captured = {}

    def fake_post(url, json=None, auth=None, headers=None, data=None):
        captured["url"] = url
        captured["json"] = json
        return FakeResp({"id": 42, "featured_media": 7})

    monkeypatch.setattr(wp_publish.requests, "post", fake_post)
    result = wp_publish.set_featured(42, str(img))
    assert captured["json"] == {"featured_media": 7}
    assert result == {"post_id": 42, "media_id": 7, "url": "https://exemplo.com/a.jpg"}
