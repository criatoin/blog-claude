"""
gmail_fetch.py — Busca emails não lidos via IMAP (Hostinger).

Mesma interface do módulo anterior (Gmail OAuth) — run_releases.py não precisa mudar.

Variáveis de ambiente:
  IMAP_HOST      — servidor IMAP (padrão: imap.hostinger.com)
  IMAP_USER      — endereço de email
  IMAP_PASSWORD  — senha do email
  IMAP_PORT      — porta SSL (padrão: 993)

Uso:
    python execution/gmail_fetch.py [--max 10] [--output-dir .tmp]

Saída JSON:
    [{"id", "subject", "sender", "date", "body_text", "body_html", "attachments"}]
"""

import argparse
import imaplib
import json
import os
import re
import sys
from datetime import datetime, timezone
from email import message_from_bytes
from email.header import decode_header
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests as _requests
from dotenv import load_dotenv

load_dotenv()

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _decode_str(value: str) -> str:
    """Decodifica header encodado (=?UTF-8?Q?...?= etc.)."""
    parts = decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def _extract_body(msg) -> tuple[str, str]:
    """Extrai body text/plain e text/html de um email."""
    text, html = "", ""

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = part.get("Content-Disposition", "")
            if "attachment" in cd:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                content = payload.decode(charset, errors="replace")
                if ct == "text/plain" and not text:
                    text = content
                elif ct == "text/html" and not html:
                    html = content
            except Exception:
                continue
    else:
        charset = msg.get_content_charset() or "utf-8"
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                content = payload.decode(charset, errors="replace")
                ct = msg.get_content_type()
                if ct == "text/plain":
                    text = content
                elif ct == "text/html":
                    html = content
        except Exception:
            pass

    return text, html


def _fetch_external_photos(body_text: str, msg_id: str, output_dir: Path) -> list[str]:
    """
    Baixa fotos de links externos no corpo do email (Flickr álbum).
    Retorna lista de caminhos salvos.
    """
    saved = []

    # Detecta links de álbum Flickr: flic.kr/s/... ou flickr.com/.../sets/...
    flickr_links = re.findall(
        r'https?://(?:flic\.kr/s/\S+|www\.flickr\.com/photos/[^\s]+/sets/[^\s]+)',
        body_text
    )
    if not flickr_links:
        return []

    album_url = flickr_links[0].strip().rstrip('/')
    print(f"[gmail_fetch] Álbum Flickr encontrado: {album_url}", file=sys.stderr)

    try:
        resp = _requests.get(
            album_url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=15,
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return []

        html = resp.text
        # Extrai IDs de foto do álbum
        user_match = re.search(r'/photos/([^/]+)/sets/', resp.url)
        if not user_match:
            return []
        flickr_user = user_match.group(1)
        photo_ids = list(dict.fromkeys(re.findall(rf'/photos/{re.escape(flickr_user)}/(\d+)/', html)))

        if not photo_ids:
            return []

        print(f"[gmail_fetch] {len(photo_ids)} fotos no álbum Flickr, baixando até 5.", file=sys.stderr)

        for i, pid in enumerate(photo_ids[:5]):
            try:
                # Pega thumbnail via oembed e converte para versão _b (large ~1024px)
                oembed = _requests.get(
                    f"https://www.flickr.com/services/oembed/?url=https://www.flickr.com/photos/{flickr_user}/{pid}&format=json",
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=10,
                )
                if oembed.status_code != 200:
                    continue
                thumb = oembed.json().get("url", "")
                if not thumb:
                    continue
                large = re.sub(r'_[a-z]\.jpg$', '_b.jpg', thumb)
                img_resp = _requests.get(large, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                if img_resp.status_code != 200 or len(img_resp.content) < 20000:
                    continue
                dest = output_dir / f"{msg_id}_flickr_{pid}.jpg"
                dest.write_bytes(img_resp.content)
                saved.append(str(dest))
                print(f"[gmail_fetch] Foto Flickr salva: {dest.name} ({len(img_resp.content)//1024}KB)", file=sys.stderr)
            except Exception as e:
                print(f"[gmail_fetch] Falha ao baixar foto Flickr {pid}: {e}", file=sys.stderr)

    except Exception as e:
        print(f"[gmail_fetch] Falha ao acessar álbum Flickr: {e}", file=sys.stderr)

    return saved


def _save_attachments(msg, msg_id: str, output_dir: Path) -> list[str]:
    """Salva anexos de imagem em output_dir. Retorna lista de caminhos."""
    saved = []
    for part in msg.walk():
        filename = part.get_filename()
        if not filename:
            continue
        filename = _decode_str(filename)
        ext = Path(filename).suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        safe_name = f"{msg_id}_{filename}"
        dest = output_dir / safe_name
        dest.write_bytes(payload)
        saved.append(str(dest))
    return saved


def fetch_emails(max_results: int, output_dir: Path) -> list[dict]:
    host = os.getenv("IMAP_HOST", "imap.hostinger.com")
    user = os.getenv("IMAP_USER", "")
    password = os.getenv("IMAP_PASSWORD", "")
    port = int(os.getenv("IMAP_PORT", "993"))

    if not user or not password:
        print("Erro: IMAP_USER e IMAP_PASSWORD devem estar no .env", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        conn = imaplib.IMAP4_SSL(host, port)
        conn.login(user, password)
        conn.select("INBOX")
    except Exception as e:
        print(f"[gmail_fetch] Falha ao conectar IMAP: {e}", file=sys.stderr)
        sys.exit(1)

    # Busca não lidos (UNSEEN)
    status, data = conn.search(None, "UNSEEN")
    if status != "OK":
        conn.logout()
        return []

    ids = data[0].split()
    # Pega os mais recentes limitado por max_results
    ids = ids[-max_results:] if len(ids) > max_results else ids

    emails = []
    for uid in ids:
        try:
            status, msg_data = conn.fetch(uid, "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                continue

            raw = msg_data[0][1]
            msg = message_from_bytes(raw)

            subject = _decode_str(msg.get("Subject", ""))
            sender = _decode_str(msg.get("From", ""))
            raw_date = msg.get("Date", "")
            message_id = msg.get("Message-ID", uid.decode()).strip()

            # Normaliza data para ISO 8601
            try:
                dt = parsedate_to_datetime(raw_date)
                date_iso = dt.astimezone(timezone.utc).isoformat()
            except Exception:
                date_iso = raw_date

            body_text, body_html = _extract_body(msg)
            attachments = _save_attachments(msg, uid.decode(), output_dir)

            # Se não há anexos de imagem, tenta baixar fotos de links externos (ex: Flickr)
            if not attachments and body_text:
                attachments = _fetch_external_photos(body_text, uid.decode(), output_dir)

            emails.append({
                "id": message_id,
                "subject": subject,
                "sender": sender,
                "date": date_iso,
                "body_text": body_text,
                "body_html": body_html,
                "attachments": attachments,
            })

            # Marca como lido para não processar novamente
            conn.store(uid, "+FLAGS", "\\Seen")

        except Exception as e:
            print(f"[gmail_fetch] Erro ao processar email {uid}: {e}", file=sys.stderr)
            continue

    conn.logout()
    return emails


def main() -> None:
    parser = argparse.ArgumentParser(description="Busca emails não lidos via IMAP")
    parser.add_argument("--max", type=int, default=10)
    parser.add_argument("--output-dir", default=".tmp")
    args = parser.parse_args()

    emails = fetch_emails(max_results=args.max, output_dir=Path(args.output_dir))
    sys.stdout.buffer.write(json.dumps(emails, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
