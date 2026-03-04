"""
telegram_bot.py — Daemon persistente de long polling do Telegram.

Responsabilidades:
  - Long polling (30s) em getUpdates
  - Callbacks publish:id:row / discard:id:row  → executa _execute_action()
  - Callbacks produce:<pauta_id>               → spawna run_pauta_produce.py em background
  - Persistência: .tmp/pending_approvals.json + .tmp/pending_pautas.json
  - answerCallbackQuery antes de qualquer ação (janela de 60s)
  - Deduplicação via seen_update_ids

Uso:
    python execution/telegram_bot.py

Deve rodar continuamente (daemon). Configure no Task Scheduler ou Docker.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent

PENDING_FILE = PROJECT_DIR / ".tmp" / "pending_approvals.json"
PENDING_PAUTAS_FILE = PROJECT_DIR / ".tmp" / "pending_pautas.json"
OFFSET_FILE = PROJECT_DIR / ".tmp" / "telegram_offset.json"

POLL_TIMEOUT = 30  # segundos de long polling


# ─── Telegram API ─────────────────────────────────────────────────────────────

def _token() -> str:
    t = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not t:
        print("Erro: TELEGRAM_BOT_TOKEN não configurado", file=sys.stderr)
        sys.exit(1)
    return t


def _chat_id() -> str:
    c = os.getenv("TELEGRAM_CHAT_ID", "")
    if not c:
        print("Erro: TELEGRAM_CHAT_ID não configurado", file=sys.stderr)
        sys.exit(1)
    return c


def _api(method: str, **kwargs) -> dict:
    url = f"https://api.telegram.org/bot{_token()}/{method}"
    http_timeout = POLL_TIMEOUT + 15
    try:
        resp = requests.post(url, timeout=http_timeout, **kwargs)
        data = resp.json()
        if not data.get("ok"):
            print(f"[bot] Telegram API erro em {method}: {data}", file=sys.stderr)
        return data
    except requests.exceptions.Timeout:
        print(f"[bot] Timeout em {method}", file=sys.stderr)
        return {"ok": False}
    except Exception as e:
        print(f"[bot] Erro em {method}: {e}", file=sys.stderr)
        return {"ok": False}


# ─── Persistência ─────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_offset() -> int:
    return _load_json(OFFSET_FILE).get("offset", 0)


def _save_offset(offset: int) -> None:
    _save_json(OFFSET_FILE, {"offset": offset})


# ─── Ações ────────────────────────────────────────────────────────────────────

def _send_text(message: str) -> None:
    """Envia mensagem de texto simples para o chat configurado."""
    _api("sendMessage", json={
        "chat_id": _chat_id(),
        "text": message,
        "parse_mode": "HTML",
    })


def _execute_action(action: str, post_id: int, sheets_row_id: str, user: str) -> dict:
    """
    Executa Publicar ou Descartar.
    Importa _execute_action de telegram_notify para reutilizar a lógica.
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    from telegram_notify import _execute_action as _notify_execute
    return _notify_execute(action, post_id, sheets_row_id, user)


def _handle_produce(pauta_id: str, cb_id: str, msg_id: str) -> None:
    """
    Captura callback produce:<pauta_id>.
    Responde imediatamente ao Telegram e lança run_pauta_produce.py em background.
    """
    # Responde ao Telegram dentro da janela de 60s
    _api("answerCallbackQuery", json={
        "callback_query_id": cb_id,
        "text": "⚙️ Produzindo pauta... aguarde o card de aprovação.",
    })

    print(f"[bot] Produzindo pauta #{pauta_id} em background...", file=sys.stderr)

    # Remove botões da mensagem de lista
    _api("editMessageReplyMarkup", json={
        "chat_id": _chat_id(),
        "message_id": int(msg_id),
        "reply_markup": json.dumps({"inline_keyboard": []}),
    })

    # Lança produção em background (não bloqueia o loop)
    subprocess.Popen(
        ["python3", str(SCRIPT_DIR / "run_pauta_produce.py"), "--pauta-id", pauta_id],
        cwd=str(PROJECT_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _handle_approval(action: str, post_id: int, sheets_row_id: str,
                     cb_id: str, msg_id: str, user: str) -> None:
    """
    Captura callbacks publish:id:row / discard:id:row.
    Só processa se msg_id estiver nos pendentes.
    """
    pending = _load_json(PENDING_FILE)
    if msg_id not in pending:
        print(f"[bot] Callback ignorado: msg_id={msg_id} não está nos pendentes.", file=sys.stderr)
        _api("answerCallbackQuery", json={"callback_query_id": cb_id, "text": "Este card já foi processado."})
        return

    # Responde ao Telegram antes de executar
    feedback = "✅ Publicando..." if action == "publish" else "🗑 Descartando..."
    _api("answerCallbackQuery", json={"callback_query_id": cb_id, "text": feedback})

    # Executa ação
    _execute_action(action, post_id, sheets_row_id, user)

    # Remove botões do card
    _api("editMessageReplyMarkup", json={
        "chat_id": _chat_id(),
        "message_id": int(msg_id),
        "reply_markup": json.dumps({"inline_keyboard": []}),
    })

    # Remove dos pendentes
    pending = _load_json(PENDING_FILE)
    pending.pop(msg_id, None)
    _save_json(PENDING_FILE, pending)


# ─── Loop principal ────────────────────────────────────────────────────────────

def run_bot() -> None:
    print("[bot] Telegram bot daemon iniciado. Aguardando callbacks...", file=sys.stderr)

    offset = _get_offset()
    seen_update_ids: set[int] = set()

    while True:
        try:
            result = _api(
                "getUpdates",
                json={
                    "offset": offset,
                    "timeout": POLL_TIMEOUT,
                    "allowed_updates": ["callback_query"],
                },
            )

            if not result.get("ok"):
                error_code = result.get("error_code", 0)
                if error_code == 409:
                    wait = POLL_TIMEOUT + 5
                    print(f"[bot] 409 Conflict — aguardando {wait}s para instância anterior expirar...", file=sys.stderr)
                    time.sleep(wait)
                else:
                    time.sleep(5)
                continue

            updates = result.get("result", [])

            for update in updates:
                update_id = update["update_id"]
                offset = update_id + 1
                _save_offset(offset)

                # Deduplicação
                if update_id in seen_update_ids:
                    continue
                seen_update_ids.add(update_id)

                # Limpa set para não crescer indefinidamente
                if len(seen_update_ids) > 10000:
                    seen_update_ids.clear()
                    seen_update_ids.add(update_id)

                cb = update.get("callback_query")
                if not cb:
                    continue

                data_str = cb.get("data", "")
                cb_id = cb["id"]
                msg_id = str(cb.get("message", {}).get("message_id", ""))
                user = cb.get("from", {}).get("first_name", "alguém")

                print(f"[bot] Callback: {data_str} (msg={msg_id}, user={user})", file=sys.stderr)

                if data_str.startswith("produce:"):
                    # Callback de produção de pauta
                    pauta_id = data_str.split(":", 1)[1]
                    _handle_produce(pauta_id, cb_id, msg_id)

                else:
                    # Callback de aprovação: publish:id:row ou discard:id:row
                    parts = data_str.split(":")
                    if len(parts) == 3:
                        action, post_id_str, sheets_row_id = parts
                        try:
                            post_id = int(post_id_str)
                        except ValueError:
                            print(f"[bot] post_id inválido: {post_id_str}", file=sys.stderr)
                            continue
                        _handle_approval(action, post_id, sheets_row_id,
                                         cb_id, msg_id, user)
                    else:
                        print(f"[bot] callback_data desconhecido: {data_str}", file=sys.stderr)
                        _api("answerCallbackQuery", json={"callback_query_id": cb_id})

        except KeyboardInterrupt:
            print("\n[bot] Encerrando por interrupção do usuário.", file=sys.stderr)
            break
        except Exception as e:
            print(f"[bot] Erro no loop: {e}", file=sys.stderr)
            time.sleep(5)


if __name__ == "__main__":
    run_bot()
