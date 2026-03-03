"""
sheets_read.py — Lê dados das abas da planilha "Operação +blog".

Uso:
    python execution/sheets_read.py pautas [--status "Pendente"]
    python execution/sheets_read.py legendas [--status "Pronta"]
    python execution/sheets_read.py log [--status "Aguardando aprovação"]
    python execution/sheets_read.py pauta-id --id 3

Saída: JSON para stdout
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
TOKEN_FILE = "token_sheets.json"

HEADERS = {
    "Log Releases": [
        "id", "origem_email", "assunto", "data_recebimento",
        "relevante", "status", "link_post", "motivo_descarte",
    ],
    "Legendas IG": [
        "id_post", "titulo", "legenda", "hashtags",
        "status", "data_postagem", "path_imagem",
    ],
    "Pautas": [
        "id", "titulo", "keyword", "categoria",
        "justificativa", "status", "slug_sugerido", "link_post",
    ],
}


def get_credentials() -> Credentials:
    # sheets_write.py pode ter salvo um token com escopo de escrita — tenta reusar
    write_token = Path("token_sheets.json")
    if write_token.exists():
        creds = Credentials.from_authorized_user_file(str(write_token))
        if creds and (creds.valid or (creds.expired and creds.refresh_token)):
            if creds.expired:
                creds.refresh(Request())
                write_token.write_text(creds.to_json())
            return creds

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        print("Erro: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET e GOOGLE_REFRESH_TOKEN necessários", file=sys.stderr)
        sys.exit(1)

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
    )
    creds.refresh(Request())
    write_token.write_text(creds.to_json())
    return creds


def get_sheets_id() -> str:
    sid = os.getenv("SHEETS_ID", "")
    if not sid:
        print("Erro: SHEETS_ID não definido no .env.", file=sys.stderr)
        sys.exit(1)
    return sid


def _read_tab(tab: str, status_filter: str | None = None) -> list[dict]:
    service = build("sheets", "v4", credentials=get_credentials())
    sid = get_sheets_id()
    headers = HEADERS[tab]

    result = service.spreadsheets().values().get(
        spreadsheetId=sid,
        range=f"'{tab}'!A:Z",
    ).execute()

    rows = result.get("values", [])
    if len(rows) <= 1:
        return []  # Apenas cabeçalho ou vazio

    # Converte linhas em dicts usando os cabeçalhos conhecidos
    records = []
    for row in rows[1:]:  # Pula cabeçalho
        padded = row + [""] * (len(headers) - len(row))
        record = dict(zip(headers, padded))

        if status_filter and record.get("status", "").lower() != status_filter.lower():
            continue

        records.append(record)

    return records


# ─── Comandos ─────────────────────────────────────────────────────────────────

def cmd_pautas(status: str | None) -> list[dict]:
    return _read_tab("Pautas", status)


def cmd_legendas(status: str | None) -> list[dict]:
    return _read_tab("Legendas IG", status)


def cmd_log(status: str | None) -> list[dict]:
    return _read_tab("Log Releases", status)


def cmd_pauta_id(pauta_id: str) -> dict | None:
    records = _read_tab("Pautas")
    for r in records:
        if str(r.get("id", "")) == str(pauta_id):
            return r
    print(f"Pauta #{pauta_id} não encontrada.", file=sys.stderr)
    sys.exit(1)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Lê dados da planilha Operação +blog")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_pt = subparsers.add_parser("pautas", help="Lista pautas")
    p_pt.add_argument("--status", default=None, help='Filtrar por status (ex: "Pendente")')

    p_ig = subparsers.add_parser("legendas", help="Lista legendas IG")
    p_ig.add_argument("--status", default=None, help='Filtrar por status (ex: "Pronta")')

    p_lg = subparsers.add_parser("log", help="Lista log de releases")
    p_lg.add_argument("--status", default=None)

    p_pid = subparsers.add_parser("pauta-id", help="Busca pauta pelo ID")
    p_pid.add_argument("--id", required=True)

    args = parser.parse_args()

    if args.command == "pautas":
        result = cmd_pautas(args.status)
    elif args.command == "legendas":
        result = cmd_legendas(args.status)
    elif args.command == "log":
        result = cmd_log(args.status)
    elif args.command == "pauta-id":
        result = cmd_pauta_id(args.id)

    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
