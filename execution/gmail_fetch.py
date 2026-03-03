"""
gmail_fetch.py — Busca emails não lidos do Gmail e salva anexos de imagem em .tmp/

Uso:
    python execution/gmail_fetch.py [--max 10] [--output-dir .tmp]

Saída: JSON para stdout com lista de emails
"""

import argparse
import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
TOKEN_FILE = "token.json"


def get_credentials() -> Credentials:
    """Obtém credenciais OAuth2, usando token salvo ou refresh token do .env."""
    creds = None

    if os.path.exists(TOKEN_FILE):
        # Não passa SCOPES para evitar invalid_scope no refresh
        creds = Credentials.from_authorized_user_file(TOKEN_FILE)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_token(creds)
        return creds

    # Constrói credenciais a partir das variáveis de ambiente
    client_id = os.getenv("GMAIL_CLIENT_ID")
    client_secret = os.getenv("GMAIL_CLIENT_SECRET")
    refresh_token = os.getenv("GMAIL_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        print(
            "Erro: GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET e GMAIL_REFRESH_TOKEN "
            "devem estar definidos no .env",
            file=sys.stderr,
        )
        sys.exit(1)

    # Não passamos scopes aqui — o token já foi autorizado com os escopos corretos.
    # Passar scopes no refresh causa 'invalid_scope' se o token original não os inclui explicitamente.
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
    )
    creds.refresh(Request())
    _save_token(creds)
    return creds


def _save_token(creds: Credentials) -> None:
    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())


def _decode_body(data: str) -> str:
    """Decodifica base64url para string UTF-8."""
    try:
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_body(payload: dict) -> tuple[str, str]:
    """Extrai body text/plain e text/html de um payload de mensagem."""
    text, html = "", ""

    def walk(part: dict) -> None:
        nonlocal text, html
        mime = part.get("mimeType", "")
        body_data = part.get("body", {}).get("data", "")

        if mime == "text/plain" and body_data:
            text = _decode_body(body_data)
        elif mime == "text/html" and body_data:
            html = _decode_body(body_data)

        for sub in part.get("parts", []):
            walk(sub)

    walk(payload)
    return text, html


def _save_attachment(service, msg_id: str, part: dict, output_dir: Path) -> str | None:
    """Baixa e salva um anexo de imagem. Retorna o caminho salvo ou None."""
    filename = part.get("filename", "")
    if not filename:
        return None

    ext = Path(filename).suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        return None

    attachment_id = part.get("body", {}).get("attachmentId")
    if not attachment_id:
        return None

    attachment = (
        service.users()
        .messages()
        .attachments()
        .get(userId="me", messageId=msg_id, id=attachment_id)
        .execute()
    )
    data = attachment.get("data", "")
    if not data:
        return None

    safe_filename = f"{msg_id}_{filename}"
    dest = output_dir / safe_filename
    dest.write_bytes(base64.urlsafe_b64decode(data + "=="))
    return str(dest)


def fetch_emails(max_results: int, output_dir: Path) -> list[dict]:
    creds = get_credentials()
    service = build("gmail", "v1", credentials=creds)

    output_dir.mkdir(parents=True, exist_ok=True)

    results = (
        service.users()
        .messages()
        .list(userId="me", labelIds=["INBOX", "UNREAD"], maxResults=max_results)
        .execute()
    )
    messages = results.get("messages", [])

    emails = []
    for msg_ref in messages:
        msg_id = msg_ref["id"]
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_id, format="full")
            .execute()
        )

        headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
        subject = headers.get("Subject", "")
        sender = headers.get("From", "")
        raw_date = headers.get("Date", "")

        # Normaliza data para ISO 8601
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(raw_date)
            date_iso = dt.astimezone(timezone.utc).isoformat()
        except Exception:
            date_iso = raw_date

        body_text, body_html = _extract_body(msg["payload"])

        # Coleta anexos de imagem
        attachments = []

        def collect_attachments(part: dict) -> None:
            if part.get("filename") and part.get("body", {}).get("attachmentId"):
                path = _save_attachment(service, msg_id, part, output_dir)
                if path:
                    attachments.append(path)
            for sub in part.get("parts", []):
                collect_attachments(sub)

        collect_attachments(msg["payload"])

        emails.append(
            {
                "id": msg_id,
                "subject": subject,
                "sender": sender,
                "date": date_iso,
                "body_text": body_text,
                "body_html": body_html,
                "attachments": attachments,
            }
        )

    return emails


def main() -> None:
    parser = argparse.ArgumentParser(description="Busca emails não lidos do Gmail")
    parser.add_argument("--max", type=int, default=10, help="Número máximo de emails (padrão: 10)")
    parser.add_argument("--output-dir", default=".tmp", help="Diretório para salvar anexos (padrão: .tmp)")
    args = parser.parse_args()

    emails = fetch_emails(max_results=args.max, output_dir=Path(args.output_dir))
    sys.stdout.buffer.write(json.dumps(emails, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
