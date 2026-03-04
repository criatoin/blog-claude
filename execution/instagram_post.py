"""
instagram_post.py — Posta imagem no Instagram via Meta Graph API.

Fluxo:
  1. Upload da imagem para WP Media (obtém URL pública)
  2. POST /{ig_user_id}/media  (cria container com image_url + caption)
  3. POST /{ig_user_id}/media_publish  (publica o container)
  4. GET /{ig_post_id}?fields=permalink  (obtém URL do post)

Env vars necessárias:
  INSTAGRAM_ACCESS_TOKEN          — token de longa duração da conta Business
  INSTAGRAM_BUSINESS_ACCOUNT_ID  — ID numérico da conta Business do IG

Uso:
    python execution/instagram_post.py post \
        --image-path .tmp/slug_ig.webp \
        --caption "Legenda do post. #hashtag" \
        --title "Alt text para WP Media"

Saída JSON:
    {"ok": true,  "ig_post_id": "17...", "url": "https://www.instagram.com/p/..."}
    {"ok": false, "error": "mensagem de erro"}
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR = Path(__file__).parent
GRAPH_URL = "https://graph.facebook.com/v19.0"


def _get_config() -> tuple[str, str]:
    """Retorna (access_token, ig_user_id) ou encerra com erro."""
    token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
    ig_id = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID", "")
    if not token or not ig_id:
        print(
            "Erro: INSTAGRAM_ACCESS_TOKEN e INSTAGRAM_BUSINESS_ACCOUNT_ID são obrigatórios",
            file=sys.stderr,
        )
        sys.exit(1)
    return token, ig_id


def _graph(method: str, endpoint: str, **kwargs) -> dict:
    """Chama a Graph API do Meta."""
    url = f"{GRAPH_URL}/{endpoint}"
    resp = getattr(requests, method)(url, timeout=30, **kwargs)
    try:
        return resp.json()
    except Exception:
        return {"error": resp.text}


def cmd_post(image_path: str, caption: str, title: str = "") -> dict:
    """Posta imagem no Instagram. Retorna dict com ok, ig_post_id, url."""
    token, ig_id = _get_config()

    # 1. Upload para WP Media → URL pública
    wp_args = [
        "python3", str(SCRIPT_DIR / "wp_publish.py"),
        "upload-image",
        "--image-path", image_path,
    ]
    if title:
        wp_args += ["--title", title]

    wp_result = subprocess.run(wp_args, capture_output=True, text=True)
    if wp_result.returncode != 0:
        err = wp_result.stderr.strip() or wp_result.stdout.strip()
        return {"ok": False, "error": f"Falha no upload WP: {err}"}

    try:
        wp_data = json.loads(wp_result.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": f"Resposta inválida do wp_publish: {wp_result.stdout}"}

    image_url = wp_data.get("url", "")
    if not image_url:
        return {"ok": False, "error": f"wp_publish não retornou URL: {wp_data}"}

    print(f"[instagram_post] Imagem enviada ao WP: {image_url}", file=sys.stderr)

    # 2. Criar container de mídia no IG
    container_resp = _graph(
        "post",
        f"{ig_id}/media",
        params={
            "image_url": image_url,
            "caption": caption,
            "access_token": token,
        },
    )
    creation_id = container_resp.get("id")
    if not creation_id:
        return {"ok": False, "error": f"Falha ao criar container IG: {container_resp}"}

    print(f"[instagram_post] Container criado: {creation_id}", file=sys.stderr)

    # 3. Publicar o container
    publish_resp = _graph(
        "post",
        f"{ig_id}/media_publish",
        params={
            "creation_id": creation_id,
            "access_token": token,
        },
    )
    ig_post_id = publish_resp.get("id")
    if not ig_post_id:
        return {"ok": False, "error": f"Falha ao publicar container IG: {publish_resp}"}

    print(f"[instagram_post] Post publicado: {ig_post_id}", file=sys.stderr)

    # 4. Buscar permalink
    permalink_resp = _graph(
        "get",
        ig_post_id,
        params={
            "fields": "permalink",
            "access_token": token,
        },
    )
    permalink = permalink_resp.get("permalink", f"https://www.instagram.com/p/{ig_post_id}/")

    return {"ok": True, "ig_post_id": ig_post_id, "url": permalink}


def main() -> None:
    parser = argparse.ArgumentParser(description="Posta imagem no Instagram via Graph API")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_post = subparsers.add_parser("post", help="Faz upload e publica imagem no IG")
    p_post.add_argument("--image-path", required=True, help="Caminho local da imagem")
    p_post.add_argument("--caption", required=True, help="Legenda do post")
    p_post.add_argument("--title", default="", help="Alt text para WP Media (opcional)")

    args = parser.parse_args()

    if args.command == "post":
        result = cmd_post(args.image_path, args.caption, args.title)

    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
