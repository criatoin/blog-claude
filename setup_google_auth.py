"""
setup_google_auth.py — Gera um novo refresh token Google com todos os escopos necessários.

Escopos incluídos:
  - Google Sheets (leitura/escrita)
  - Google Search Console (leitura)
  - Google Analytics 4 (leitura)

Uso:
    python setup_google_auth.py

Abre o navegador para autorização. Após autorizar, exibe o novo GOOGLE_REFRESH_TOKEN
para copiar no .env.
"""

import json
import os
import sys

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/analytics.readonly",
]


def main() -> None:
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("Erro: GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET devem estar no .env", file=sys.stderr)
        sys.exit(1)

    # Monta o client_config no formato aceito pelo InstalledAppFlow
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)

    print("\nAbrindo navegador para autorização Google...")
    print("Certifique-se de estar logado com a conta que tem acesso ao GSC e GA4.\n")

    # prompt=select_account força o Google a perguntar qual conta usar
    creds = flow.run_local_server(port=0, open_browser=True, prompt="select_account")

    print("\n" + "=" * 60)
    print("✅ Autorização concluída!")
    print("=" * 60)
    print(f"\nNovo GOOGLE_REFRESH_TOKEN:\n{creds.refresh_token}")
    print("\nCopie e substitua o valor de GOOGLE_REFRESH_TOKEN no arquivo .env")
    print("=" * 60)

    # Salva token_sheets.json (já válido com novos escopos)
    with open("token_sheets.json", "w") as f:
        f.write(creds.to_json())
    print("\ntoken_sheets.json atualizado com os novos escopos.")


if __name__ == "__main__":
    main()
