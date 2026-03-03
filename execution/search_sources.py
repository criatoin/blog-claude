"""
search_sources.py — Busca fontes confiáveis sobre um tema usando Tavily.

Retorna 3–5 fontes relevantes com título, URL e trecho para embasar pautas
produzidas pelo agente. Se não encontrar fontes mínimas, sinaliza para o
agente marcar a pauta como "Sem fontes".

Autenticação: TAVILY_API_KEY no .env

Uso:
    python execution/search_sources.py --query "show de jazz americana sp" [--max 5]
    python execution/search_sources.py --query "teatro sbo prefeitura" --min-score 0.5

Saída: JSON para stdout com lista de fontes e flag sufficient (true/false)
"""

import argparse
import json
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

TAVILY_API_URL = "https://api.tavily.com/search"

# Domínios preferidos: portais de prefeituras, governo, portais locais
PREFERRED_DOMAINS = [
    "americana.sp.gov.br",
    "sbodoeste.sp.gov.br",
    "novaodessa.sp.gov.br",
    "sumare.sp.gov.br",
    "sp.gov.br",
    "gov.br",
    "maisblog.com.br",
    "campinas.com.br",
    "g1.globo.com",
    "folha.uol.com.br",
]


def search_sources(
    query: str,
    max_results: int,
    min_score: float,
) -> dict:
    """
    Busca fontes usando Tavily e retorna resultado com flag sufficient.
    sufficient = True se encontrou pelo menos 2 fontes com score >= min_score.
    """
    api_key = os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        print("Erro: TAVILY_API_KEY não configurado no .env", file=sys.stderr)
        sys.exit(1)

    headers = {"Content-Type": "application/json"}
    body = {
        "api_key": api_key,
        "query": query,
        "search_depth": "advanced",
        "max_results": max_results + 3,  # pede um pouco mais para ter margem de filtro
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
    }

    try:
        resp = requests.post(TAVILY_API_URL, json=body, headers=headers, timeout=30)
        data = resp.json()
    except Exception as e:
        print(f"Erro ao chamar Tavily API: {e}", file=sys.stderr)
        sys.exit(1)

    if "error" in data:
        print(f"Tavily erro: {data['error']}", file=sys.stderr)
        sys.exit(1)

    raw_results = data.get("results", [])

    sources = []
    for item in raw_results:
        score = item.get("score", 0.0)
        if score < min_score:
            continue
        sources.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("content", "")[:500],  # trunca para 500 chars
            "score": round(score, 3),
            "published_date": item.get("published_date", ""),
        })
        if len(sources) >= max_results:
            break

    sufficient = len(sources) >= 2

    return {
        "query": query,
        "sufficient": sufficient,
        "count": len(sources),
        "sources": sources,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tavily — busca fontes confiáveis para pautas"
    )
    parser.add_argument("--query", required=True, help="Termo de busca")
    parser.add_argument(
        "--max", type=int, default=5,
        help="Número máximo de fontes (padrão: 5)",
    )
    parser.add_argument(
        "--min-score", type=float, default=0.4,
        help="Score mínimo de relevância 0–1 (padrão: 0.4)",
    )
    args = parser.parse_args()

    result = search_sources(
        query=args.query,
        max_results=args.max,
        min_score=args.min_score,
    )

    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
