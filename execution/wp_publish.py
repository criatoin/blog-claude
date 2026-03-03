"""
wp_publish.py — Cria, publica, move para lixeira posts e faz upload de imagens no WordPress.

Uso:
    python execution/wp_publish.py create --title "Título" --html "<p>corpo</p>" [--image-path .tmp/img.webp] [--category-id 5]
    python execution/wp_publish.py publish --post-id 123
    python execution/wp_publish.py trash --post-id 123
    python execution/wp_publish.py upload-image --image-path .tmp/img.webp --title "Alt text"

Saída: JSON para stdout
"""

import argparse
import json
import mimetypes
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()


def get_config() -> tuple[str, tuple[str, str]]:
    """Retorna (wp_url, auth) ou encerra com erro."""
    url = os.getenv("WP_URL", "").rstrip("/")
    user = os.getenv("WP_USER", "")
    password = os.getenv("WP_APP_PASSWORD", "")

    if not all([url, user, password]):
        print(
            "Erro: WP_URL, WP_USER e WP_APP_PASSWORD devem estar definidos no .env",
            file=sys.stderr,
        )
        sys.exit(1)

    return url, (user, password)


def _check_response(resp: requests.Response) -> dict:
    """Verifica resposta da API; encerra com erro se falhar."""
    if not resp.ok:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        print(f"Erro da API WordPress ({resp.status_code}): {detail}", file=sys.stderr)
        sys.exit(1)
    return resp.json()


def upload_image(image_path: str, title: str = "") -> dict:
    """Faz upload de uma imagem para a Media Library. Retorna dict com media_id."""
    wp_url, auth = get_config()
    path = Path(image_path)

    if not path.exists():
        print(f"Erro: arquivo não encontrado: {image_path}", file=sys.stderr)
        sys.exit(1)

    mime_type, _ = mimetypes.guess_type(str(path))
    if not mime_type:
        mime_type = "application/octet-stream"

    headers = {
        "Content-Disposition": f'attachment; filename="{path.name}"',
        "Content-Type": mime_type,
    }

    with path.open("rb") as f:
        resp = requests.post(
            f"{wp_url}/wp-json/wp/v2/media",
            headers=headers,
            data=f,
            auth=auth,
        )

    data = _check_response(resp)

    if title:
        # Atualiza alt_text e title após o upload
        requests.post(
            f"{wp_url}/wp-json/wp/v2/media/{data['id']}",
            json={"title": title, "alt_text": title},
            auth=auth,
        )

    return {"media_id": data["id"], "url": data.get("source_url", "")}


def create_post(title: str, html: str, image_path: str = "", category_id: int = 0) -> dict:
    """Cria um rascunho no WordPress. Retorna dict com post_id, status, url, edit_url."""
    wp_url, auth = get_config()

    media_id = None
    if image_path:
        result = upload_image(image_path)
        media_id = result["media_id"]

    payload: dict = {
        "title": title,
        "content": html,
        "status": "draft",
    }
    if media_id:
        payload["featured_media"] = media_id
    if category_id:
        payload["categories"] = [category_id]

    resp = requests.post(f"{wp_url}/wp-json/wp/v2/posts", json=payload, auth=auth)
    data = _check_response(resp)

    return {
        "post_id": data["id"],
        "status": data["status"],
        "url": data.get("link", ""),
        "edit_url": f"{wp_url}/wp-admin/post.php?post={data['id']}&action=edit",
    }


def publish_post(post_id: int) -> dict:
    """Publica um post existente."""
    wp_url, auth = get_config()

    resp = requests.post(
        f"{wp_url}/wp-json/wp/v2/posts/{post_id}",
        json={"status": "publish"},
        auth=auth,
    )
    data = _check_response(resp)

    return {
        "post_id": data["id"],
        "status": data["status"],
        "url": data.get("link", ""),
        "edit_url": f"{wp_url}/wp-admin/post.php?post={data['id']}&action=edit",
    }


def trash_post(post_id: int) -> dict:
    """Move um post para a lixeira."""
    wp_url, auth = get_config()

    resp = requests.delete(f"{wp_url}/wp-json/wp/v2/posts/{post_id}", auth=auth)
    data = _check_response(resp)

    return {
        "post_id": data["id"],
        "status": data.get("status", "trash"),
        "url": data.get("link", ""),
        "edit_url": f"{wp_url}/wp-admin/post.php?post={data['id']}&action=edit",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Gerencia posts no WordPress via REST API")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # create
    p_create = subparsers.add_parser("create", help="Cria um rascunho")
    p_create.add_argument("--title", required=True)
    p_create.add_argument("--html", required=True)
    p_create.add_argument("--image-path", default="")
    p_create.add_argument("--category-id", type=int, default=0)

    # publish
    p_publish = subparsers.add_parser("publish", help="Publica um post")
    p_publish.add_argument("--post-id", type=int, required=True)

    # trash
    p_trash = subparsers.add_parser("trash", help="Move post para lixeira")
    p_trash.add_argument("--post-id", type=int, required=True)

    # upload-image
    p_upload = subparsers.add_parser("upload-image", help="Faz upload de imagem")
    p_upload.add_argument("--image-path", required=True)
    p_upload.add_argument("--title", default="")

    args = parser.parse_args()

    if args.command == "create":
        result = create_post(args.title, args.html, args.image_path, args.category_id)
    elif args.command == "publish":
        result = publish_post(args.post_id)
    elif args.command == "trash":
        result = trash_post(args.post_id)
    elif args.command == "upload-image":
        result = upload_image(args.image_path, args.title)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
