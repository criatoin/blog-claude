"""
gsc_report.py — Busca top queries do Google Search Console com gap de CTR.

Gap de CTR: queries com muitas impressões mas poucos cliques — indicam que o
conteúdo do site não atende bem a intenção de busca, ou não existe conteúdo
para o tema. São as melhores oportunidades de pauta.

Autenticação: OAuth2 via GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN
Site: GSC_SITE_URL no .env (ex: https://maisblog.com.br/)

Uso:
    python execution/gsc_report.py [--site https://maisblog.com.br/] [--days 90] [--max 20]
    python execution/gsc_report.py --min-impressions 30 --max-ctr 5

Saída: JSON para stdout com lista de queries ordenadas por impressões
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
TOKEN_FILE = "token_gsc.json"


def get_credentials() -> Credentials:
    """Obtém credenciais OAuth2 para o Search Console."""
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_token(creds)
        return creds

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        print(
            "Erro: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET e GOOGLE_REFRESH_TOKEN "
            "devem estar no .env",
            file=sys.stderr,
        )
        sys.exit(1)

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    try:
        creds.refresh(Request())
    except Exception as e:
        print(
            f"Erro ao autenticar Google Search Console: {e}\n"
            "Verifique se o GOOGLE_REFRESH_TOKEN tem escopo 'webmasters.readonly'.\n"
            "Se não tiver, gere um novo token com o escopo correto.",
            file=sys.stderr,
        )
        sys.exit(1)
    _save_token(creds)
    return creds


def _save_token(creds: Credentials) -> None:
    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())


def fetch_gsc_queries(
    site_url: str,
    days: int,
    max_results: int,
    min_impressions: int,
    max_ctr_pct: float,
) -> list[dict]:
    """
    Retorna queries com impressões >= min_impressions e CTR < max_ctr_pct%.
    Ordenadas por impressões descendentes.
    """
    creds = get_credentials()
    service = build("searchconsole", "v1", credentials=creds)

    # GSC tem delay de ~3 dias
    end_date = datetime.now() - timedelta(days=3)
    start_date = end_date - timedelta(days=days)

    request_body = {
        "startDate": start_date.strftime("%Y-%m-%d"),
        "endDate": end_date.strftime("%Y-%m-%d"),
        "dimensions": ["query"],
        "rowLimit": 1000,
    }

    try:
        response = (
            service.searchanalytics()
            .query(siteUrl=site_url, body=request_body)
            .execute()
        )
    except Exception as e:
        print(f"Erro ao chamar Search Console API: {e}", file=sys.stderr)
        sys.exit(1)

    rows = response.get("rows", [])

    max_ctr_fraction = max_ctr_pct / 100.0
    filtered = []
    for row in rows:
        query = row["keys"][0]
        impressions = int(row.get("impressions", 0))
        clicks = int(row.get("clicks", 0))
        ctr = row.get("ctr", 0.0)
        position = row.get("position", 0.0)

        if impressions >= min_impressions and ctr < max_ctr_fraction:
            filtered.append({
                "query": query,
                "impressions": impressions,
                "clicks": clicks,
                "ctr_pct": round(ctr * 100, 2),
                "position": round(position, 1),
            })

    filtered.sort(key=lambda x: x["impressions"], reverse=True)
    return filtered[:max_results]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Google Search Console — queries com gap de CTR"
    )
    parser.add_argument(
        "--site",
        default=None,
        help="URL do site no GSC (padrão: GSC_SITE_URL do .env)",
    )
    parser.add_argument(
        "--days", type=int, default=90,
        help="Janela de dias a analisar (padrão: 90)",
    )
    parser.add_argument(
        "--max", type=int, default=20,
        help="Máximo de queries retornadas (padrão: 20)",
    )
    parser.add_argument(
        "--min-impressions", type=int, default=50,
        help="Mínimo de impressões para incluir a query (padrão: 50)",
    )
    parser.add_argument(
        "--max-ctr", type=float, default=3.0,
        help="CTR máximo em %% para considerar gap (padrão: 3.0)",
    )
    args = parser.parse_args()

    site_url = args.site or os.getenv("GSC_SITE_URL", "https://maisblog.com.br/")

    queries = fetch_gsc_queries(
        site_url=site_url,
        days=args.days,
        max_results=args.max,
        min_impressions=args.min_impressions,
        max_ctr_pct=args.max_ctr,
    )

    sys.stdout.buffer.write(json.dumps(queries, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
