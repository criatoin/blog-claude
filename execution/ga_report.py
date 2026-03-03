"""
ga_report.py — Busca os posts mais visitados no Google Analytics 4 (últimos N dias).

Identifica os temas em alta no portal para orientar a geração de pautas.

Autenticação: OAuth2 via GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN
Property: GA4_PROPERTY_ID no .env (ex: 123456789)

Uso:
    python execution/ga_report.py [--days 30] [--max 10]
    python execution/ga_report.py --days 7 --max 5

Saída: JSON para stdout com lista de posts ordenados por pageviews
"""

import argparse
import json
import os
import sys

import requests
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
TOKEN_FILE = "token_ga.json"


def get_credentials() -> Credentials:
    """Obtém credenciais OAuth2 para o Google Analytics."""
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
            f"Erro ao autenticar Google Analytics: {e}\n"
            "Verifique se o GOOGLE_REFRESH_TOKEN tem escopo 'analytics.readonly'.\n"
            "Se não tiver, gere um novo token com o escopo correto.",
            file=sys.stderr,
        )
        sys.exit(1)
    _save_token(creds)
    return creds


def _save_token(creds: Credentials) -> None:
    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())


def fetch_top_posts(property_id: str, days: int, max_results: int) -> list[dict]:
    """
    Retorna os posts mais visitados do GA4 na janela de `days` dias.
    Usa a GA4 Data API via REST (sem dependência do SDK google-analytics-data).
    """
    creds = get_credentials()

    url = f"https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport"
    headers = {"Authorization": f"Bearer {creds.token}"}

    body = {
        "dateRanges": [{"startDate": f"{days}daysAgo", "endDate": "today"}],
        "dimensions": [
            {"name": "pagePath"},
            {"name": "pageTitle"},
        ],
        "metrics": [
            {"name": "screenPageViews"},
            {"name": "sessions"},
        ],
        "orderBys": [
            {"metric": {"metricName": "screenPageViews"}, "desc": True}
        ],
        "limit": max_results,
        # Filtra páginas reais (exclui home, tag, categoria)
        "dimensionFilter": {
            "andGroup": {
                "expressions": [
                    {
                        "notExpression": {
                            "filter": {
                                "fieldName": "pagePath",
                                "stringFilter": {
                                    "matchType": "EXACT",
                                    "value": "/"
                                }
                            }
                        }
                    },
                    {
                        "notExpression": {
                            "filter": {
                                "fieldName": "pagePath",
                                "stringFilter": {
                                    "matchType": "BEGINS_WITH",
                                    "value": "/tag/"
                                }
                            }
                        }
                    },
                    {
                        "notExpression": {
                            "filter": {
                                "fieldName": "pagePath",
                                "stringFilter": {
                                    "matchType": "BEGINS_WITH",
                                    "value": "/category/"
                                }
                            }
                        }
                    },
                ]
            }
        },
    }

    try:
        resp = requests.post(url, json=body, headers=headers, timeout=30)
        data = resp.json()
    except Exception as e:
        print(f"Erro ao chamar GA4 API: {e}", file=sys.stderr)
        sys.exit(1)

    if "error" in data:
        print(f"GA4 API erro: {data['error']}", file=sys.stderr)
        sys.exit(1)

    rows = data.get("rows", [])
    results = []
    for row in rows:
        path = row["dimensionValues"][0]["value"]
        title = row["dimensionValues"][1]["value"]
        views = int(row["metricValues"][0]["value"])
        sessions = int(row["metricValues"][1]["value"])
        results.append({
            "path": path,
            "title": title,
            "views": views,
            "sessions": sessions,
        })

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Google Analytics 4 — posts mais visitados"
    )
    parser.add_argument(
        "--days", type=int, default=30,
        help="Janela de dias a analisar (padrão: 30)",
    )
    parser.add_argument(
        "--max", type=int, default=10,
        help="Número máximo de posts retornados (padrão: 10)",
    )
    parser.add_argument(
        "--property",
        default=None,
        help="GA4 Property ID (padrão: GA4_PROPERTY_ID do .env)",
    )
    args = parser.parse_args()

    property_id = args.property or os.getenv("GA4_PROPERTY_ID", "")
    if not property_id:
        print(
            "Erro: GA4_PROPERTY_ID não configurado. "
            "Adicione ao .env ou use --property.",
            file=sys.stderr,
        )
        sys.exit(1)

    posts = fetch_top_posts(
        property_id=property_id,
        days=args.days,
        max_results=args.max,
    )

    sys.stdout.buffer.write(json.dumps(posts, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
