"""
sheets_write.py — Escreve dados nas abas da planilha "Operação +blog".

Abas:
  Log Releases  — registra cada email processado
  Legendas IG   — salva legendas e artes geradas
  Pautas        — salva sugestões de pauta

Autenticação: OAuth2 via GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN
Planilha: SHEETS_ID no .env

Uso:
    # Configura planilha do zero (cria abas e cabeçalhos — rodar 1x)
    python execution/sheets_write.py setup

    # Registra release processado
    python execution/sheets_write.py log-release --data '{...}'

    # Registra legenda do Instagram
    python execution/sheets_write.py legenda-ig --data '{...}'

    # Registra sugestão de pauta
    python execution/sheets_write.py pauta --data '{...}'

    # Atualiza status de uma linha pelo ID
    python execution/sheets_write.py update-status --tab "Log Releases" --row-id "19cb54a2" --status "Publicado"
"""

import argparse
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

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
TOKEN_FILE = "token_sheets.json"

# Cabeçalhos de cada aba
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
    creds = None
    if Path(TOKEN_FILE).exists():
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        Path(TOKEN_FILE).write_text(creds.to_json())
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
    Path(TOKEN_FILE).write_text(creds.to_json())
    return creds


def get_sheets_id() -> str:
    sid = os.getenv("SHEETS_ID", "")
    if not sid:
        print("Erro: SHEETS_ID não definido no .env. Rode 'python execution/sheets_write.py setup' primeiro.", file=sys.stderr)
        sys.exit(1)
    return sid


def get_service():
    return build("sheets", "v4", credentials=get_credentials())


# ─── Setup ────────────────────────────────────────────────────────────────────

def cmd_setup() -> dict:
    """Cria a planilha 'Operação +blog' com as 3 abas e cabeçalhos."""
    creds = get_credentials()
    drive_service = build("drive", "v3", credentials=creds)
    sheets_service = build("sheets", "v4", credentials=creds)

    # Verifica se já existe SHEETS_ID configurado
    existing_id = os.getenv("SHEETS_ID", "")
    if existing_id:
        print(f"Planilha já configurada: {existing_id}", file=sys.stderr)
        return {"sheets_id": existing_id, "action": "already_exists"}

    # Cria a planilha
    body = {
        "properties": {"title": "Operação +blog"},
        "sheets": [
            {"properties": {"title": tab}} for tab in HEADERS.keys()
        ],
    }
    result = sheets_service.spreadsheets().create(body=body, fields="spreadsheetId").execute()
    sheets_id = result["spreadsheetId"]

    # Escreve cabeçalhos em cada aba
    data = []
    for tab, headers in HEADERS.items():
        data.append({
            "range": f"'{tab}'!A1",
            "values": [headers],
        })

    sheets_service.spreadsheets().values().batchUpdate(
        spreadsheetId=sheets_id,
        body={"valueInputOption": "RAW", "data": data},
    ).execute()

    print(f"\nPlanilha criada! ID: {sheets_id}", file=sys.stderr)
    print(f"Adicione ao .env: SHEETS_ID={sheets_id}", file=sys.stderr)

    return {"sheets_id": sheets_id, "action": "created"}


# ─── Append helpers ───────────────────────────────────────────────────────────

def _append_row(tab: str, row: list) -> dict:
    service = get_sheets_service()
    sid = get_sheets_id()
    result = service.spreadsheets().values().append(
        spreadsheetId=sid,
        range=f"'{tab}'!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()
    return {"tab": tab, "updated_rows": result.get("updates", {}).get("updatedRows", 1)}


def get_sheets_service():
    return build("sheets", "v4", credentials=get_credentials())


def _next_id(tab: str) -> int:
    """Retorna o próximo ID numérico para uma aba."""
    service = get_sheets_service()
    sid = get_sheets_id()
    result = service.spreadsheets().values().get(
        spreadsheetId=sid,
        range=f"'{tab}'!A:A",
    ).execute()
    values = result.get("values", [])
    # Primeira linha é cabeçalho, restantes são dados
    data_rows = [v for v in values[1:] if v and v[0].isdigit()] if len(values) > 1 else []
    return len(data_rows) + 1


# ─── Comandos ─────────────────────────────────────────────────────────────────

def cmd_log_release(data: dict) -> dict:
    next_id = _next_id("Log Releases")
    row = [
        str(next_id),
        data.get("sender", ""),
        data.get("subject", ""),
        data.get("date", datetime.now(timezone.utc).isoformat()),
        "Sim" if data.get("relevante", True) else "Não",
        data.get("status", "Aguardando aprovação"),
        data.get("link_post", ""),
        data.get("motivo_descarte", ""),
    ]
    result = _append_row("Log Releases", row)
    result["row_id"] = str(next_id)
    return result


def cmd_legenda_ig(data: dict) -> dict:
    row = [
        str(data.get("id_post", "")),
        data.get("titulo", ""),
        data.get("legenda", ""),
        data.get("hashtags", ""),
        data.get("status", "Pronta"),
        data.get("data_postagem", ""),
        data.get("path_imagem", ""),
    ]
    return _append_row("Legendas IG", row)


def cmd_pauta(data: dict) -> dict:
    next_id = _next_id("Pautas")
    row = [
        str(next_id),
        data.get("titulo", ""),
        data.get("keyword", ""),
        data.get("categoria", ""),
        data.get("justificativa", ""),
        data.get("status", "Pendente"),
        data.get("slug_sugerido", ""),
        data.get("link_post", ""),
    ]
    result = _append_row("Pautas", row)
    result["row_id"] = str(next_id)
    return result


def cmd_update_status(tab: str, row_id: str, status: str) -> dict:
    """Atualiza o campo 'status' da linha cujo ID (coluna A) seja row_id."""
    service = get_sheets_service()
    sid = get_sheets_id()

    result = service.spreadsheets().values().get(
        spreadsheetId=sid,
        range=f"'{tab}'!A:A",
    ).execute()
    values = result.get("values", [])

    row_number = None
    for i, row in enumerate(values):
        if row and str(row[0]) == str(row_id):
            row_number = i + 1  # 1-indexed
            break

    if row_number is None:
        print(f"Erro: ID '{row_id}' não encontrado na aba '{tab}'", file=sys.stderr)
        sys.exit(1)

    # Encontra coluna de status (sempre a 6ª coluna = F, index 5)
    headers = HEADERS.get(tab, [])
    try:
        status_col_idx = headers.index("status")
    except ValueError:
        status_col_idx = 5

    col_letter = chr(ord("A") + status_col_idx)
    cell = f"'{tab}'!{col_letter}{row_number}"

    service.spreadsheets().values().update(
        spreadsheetId=sid,
        range=cell,
        valueInputOption="RAW",
        body={"values": [[status]]},
    ).execute()

    return {"tab": tab, "row_id": row_id, "status": status, "cell": cell}


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Escreve dados na planilha Operação +blog")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("setup", help="Cria planilha com abas e cabeçalhos (rodar 1x)")

    p_lr = subparsers.add_parser("log-release", help="Registra release no log")
    p_lr.add_argument("--data", required=True, help="JSON com campos do release")

    p_ig = subparsers.add_parser("legenda-ig", help="Salva legenda do Instagram")
    p_ig.add_argument("--data", required=True, help="JSON com campos da legenda")

    p_pt = subparsers.add_parser("pauta", help="Salva sugestão de pauta")
    p_pt.add_argument("--data", required=True, help="JSON com campos da pauta")

    p_us = subparsers.add_parser("update-status", help="Atualiza status de uma linha")
    p_us.add_argument("--tab", required=True)
    p_us.add_argument("--row-id", required=True)
    p_us.add_argument("--status", required=True)

    args = parser.parse_args()

    if args.command == "setup":
        result = cmd_setup()
    elif args.command == "log-release":
        result = cmd_log_release(json.loads(args.data))
    elif args.command == "legenda-ig":
        result = cmd_legenda_ig(json.loads(args.data))
    elif args.command == "pauta":
        result = cmd_pauta(json.loads(args.data))
    elif args.command == "update-status":
        result = cmd_update_status(args.tab, args.row_id, args.status)

    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
