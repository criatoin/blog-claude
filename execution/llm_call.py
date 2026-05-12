"""
llm_call.py — Wrapper sobre OpenRouter API para chamadas LLM (DeepSeek por padrão).

Autenticação: OPENROUTER_API_KEY no .env

Uso:
    from execution.llm_call import llm_call
    resposta = llm_call(system="Você é...", user="Faça X")

    # Ou via linha de comando (teste):
    python execution/llm_call.py

Configuração:
    OPENROUTER_API_KEY  — obrigatório
    OPENROUTER_MODEL    — opcional, padrão: deepseek/deepseek-chat
"""

import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "deepseek/deepseek-chat"
TIMEOUT_SECS = 60
MAX_RETRIES = 3


def llm_call(
    system: str,
    user: str,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> str:
    """
    Chama a OpenRouter API e retorna o texto da resposta.

    Args:
        system: Prompt de sistema (instruções ao modelo)
        user: Prompt do usuário (conteúdo/tarefa)
        model: Modelo a usar (padrão: OPENROUTER_MODEL env var ou deepseek/deepseek-chat)
        temperature: Temperatura da geração (padrão: 0.3 para respostas mais determinísticas)

    Returns:
        String com o texto gerado pelo modelo

    Raises:
        RuntimeError: Se todas as tentativas falharem
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY não configurado no .env")

    model_id = model or os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.getenv("WP_URL", "https://maisblog.com.br"),
        "X-Title": "+blog autonomo",
    }

    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(
                OPENROUTER_API_URL,
                headers=headers,
                json=payload,
                timeout=TIMEOUT_SECS,
            )
            resp.raise_for_status()
            data = resp.json()

            choices = data.get("choices", [])
            if not choices:
                raise RuntimeError(f"Resposta sem choices: {data}")

            text = choices[0].get("message", {}).get("content", "")
            if not text:
                raise RuntimeError(f"Resposta com content vazio: {data}")

            return text.strip()

        except requests.exceptions.Timeout as e:
            last_error = e
            print(f"[llm_call] Timeout na tentativa {attempt}/{MAX_RETRIES}", file=sys.stderr)
        except requests.exceptions.HTTPError as e:
            last_error = e
            status = e.response.status_code if e.response else "?"
            print(f"[llm_call] HTTP {status} na tentativa {attempt}/{MAX_RETRIES}: {e}", file=sys.stderr)
            # Rate limit — aguarda mais antes de tentar novamente
            if e.response and e.response.status_code == 429:
                time.sleep(30)
                continue
        except Exception as e:
            last_error = e
            print(f"[llm_call] Erro na tentativa {attempt}/{MAX_RETRIES}: {e}", file=sys.stderr)

        if attempt < MAX_RETRIES:
            wait = 2 ** attempt  # backoff exponencial: 2s, 4s
            print(f"[llm_call] Aguardando {wait}s antes de tentar novamente...", file=sys.stderr)
            time.sleep(wait)

    raise RuntimeError(f"llm_call falhou após {MAX_RETRIES} tentativas: {last_error}")


def llm_call_json(system: str, user: str, model: str | None = None) -> dict | list:
    """
    Variante que extrai e parseia JSON da resposta do modelo.
    Remove blocos ```json ... ``` se presentes.

    Returns:
        dict ou list parseado do JSON

    Raises:
        RuntimeError: Se não conseguir parsear JSON
    """
    raw = llm_call(system=system, user=user, model=model)
    text = raw.strip()

    def _extract_json_block(s: str) -> str:
        """Extrai conteúdo de bloco ```json ... ``` ou retorna a string original."""
        import re as _re
        # Procura bloco ```json ... ``` mesmo com texto antes
        m = _re.search(r"```(?:json)?\s*\n([\s\S]*?)```", s)
        if m:
            return m.group(1).strip()
        # Tenta extrair JSON bruto entre { ou [ e o fechamento correspondente
        for start_ch, end_ch in (("{", "}"), ("[", "]")):
            idx = s.find(start_ch)
            if idx != -1:
                # Encontra o fechamento correto contando profundidade
                depth = 0
                in_str = False
                end_idx = -1
                for i, ch in enumerate(s[idx:], start=idx):
                    if ch == '"' and (i == 0 or s[i-1] != "\\"):
                        in_str = not in_str
                    if not in_str:
                        if ch == start_ch:
                            depth += 1
                        elif ch == end_ch:
                            depth -= 1
                            if depth == 0:
                                end_idx = i
                                break
                if end_idx != -1:
                    return s[idx:end_idx+1]
        return s

    def _escape_newlines_in_strings(s: str) -> str:
        """Substitui \n literais dentro de strings JSON por \\n."""
        result = []
        in_string = False
        i = 0
        while i < len(s):
            ch = s[i]
            if ch == '"' and (i == 0 or s[i-1] != "\\"):
                in_string = not in_string
                result.append(ch)
            elif in_string and ch == "\n":
                result.append("\\n")
            elif in_string and ch == "\r":
                result.append("\\r")
            else:
                result.append(ch)
            i += 1
        return "".join(result)

    # Tentativa 1: parse direto
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Tentativa 2: extrai bloco JSON e tenta parse
    extracted = _extract_json_block(text)
    try:
        return json.loads(extracted)
    except json.JSONDecodeError:
        pass

    # Tentativa 3: escapa \n literais dentro de strings e tenta parse
    try:
        return json.loads(_escape_newlines_in_strings(extracted))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Resposta não é JSON válido: {e}\nTexto: {text[:500]}")


# ─── Teste de linha de comando ─────────────────────────────────────────────────

if __name__ == "__main__":
    print("Testando llm_call com DeepSeek via OpenRouter...", file=sys.stderr)
    try:
        resposta = llm_call(
            system="Você é um assistente útil. Responda de forma muito breve.",
            user="Qual é a capital do Brasil? Responda em uma frase.",
        )
        print(f"Resposta: {resposta}")
        print("\nTeste de llm_call_json...")
        resultado = llm_call_json(
            system="Você é um assistente que responde apenas em JSON.",
            user='Retorne um JSON com campos "cidade" e "pais" para a capital do Brasil.',
        )
        print(f"JSON: {json.dumps(resultado, ensure_ascii=False, indent=2)}")
        print("\nTeste concluído com sucesso.")
    except RuntimeError as e:
        print(f"Erro: {e}", file=sys.stderr)
        sys.exit(1)
