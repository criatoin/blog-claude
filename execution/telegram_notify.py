"""
telegram_notify.py — Envia notificações para o Telegram com botões inline
e processa as respostas ([✅ Site] / [📸 Instagram] / [🗑 Descartar]).

Botão Instagram: marca status "Aprovado" na aba Legendas IG da planilha.
O usuário posta manualmente a partir da planilha (sem API do Instagram).

Autenticação: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID no .env

Uso:
    # Envia card de aprovação de release (com botão IG opcional)
    python execution/telegram_notify.py send-release \
        --post-id 123 \
        --title "Título do post" \
        --summary "Resumo em 2-3 linhas" \
        --edit-url "https://maisblog.com.br/wp-admin/..." \
        --cover ".tmp/slug_cover.webp" \
        --sheets-row-id 1 \
        [--ig-image ".tmp/slug_ig.webp"] \
        [--ig-caption "Legenda IG. #hashtag"]

    # Envia mensagem de texto simples
    python execution/telegram_notify.py send-text --message "Texto aqui"

    # Escuta callbacks e executa ações (Publicar/Descartar)
    # Roda por até --timeout segundos esperando respostas pendentes
    python execution/telegram_notify.py listen [--timeout 1800]

Aprovações pendentes ficam em .tmp/pending_approvals.json
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

PENDING_FILE = Path(".tmp/pending_approvals.json")
PENDING_PAUTAS_FILE = Path(".tmp/pending_pautas.json")


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


def _api(method: str, poll_timeout: int = 0, **kwargs) -> dict:
    """Chama a Bot API do Telegram.
    poll_timeout: tempo de long polling do getUpdates (o requests timeout deve ser maior).
    """
    url = f"https://api.telegram.org/bot{_token()}/{method}"
    # Garante que o timeout HTTP seja 10s maior que o poll do Telegram
    http_timeout = max(30, poll_timeout + 10)
    resp = requests.post(url, timeout=http_timeout, **kwargs)
    data = resp.json()
    if not data.get("ok"):
        print(f"Telegram API erro em {method}: {data}", file=sys.stderr)
    return data


# ─── Pending approvals (estado persistido em .tmp/) ──────────────────────────

def _load_pending() -> dict:
    if PENDING_FILE.exists():
        return json.loads(PENDING_FILE.read_text(encoding="utf-8"))
    return {}


def _save_pending(data: dict) -> None:
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ─── Helper de botões restantes ───────────────────────────────────────────────

def _build_remaining_buttons(entry: dict) -> list[list[dict]]:
    """
    Reconstrói a linha de botões com base nos flags published_site / published_ig.
    Regra: Descartar desaparece assim que Site ou IG forem publicados.
    Retorna lista de linhas (inline_keyboard) — pode ser vazia se não sobrar nada.
    """
    post_id = entry["post_id"]
    row_id = entry["sheets_row_id"]
    published_site = entry.get("published_site", False)
    published_ig = entry.get("published_ig", False)
    has_ig = bool(entry.get("ig_image_path", ""))

    row = []
    if not published_site:
        row.append({"text": "✅ Site", "callback_data": f"publish:{post_id}:{row_id}"})
    if has_ig and not published_ig:
        row.append({"text": "📸 Instagram", "callback_data": f"publish_ig:{post_id}:{row_id}"})

    # Descartar só aparece enquanto nenhuma publicação foi feita
    if not published_site and not published_ig:
        row.append({"text": "🗑 Descartar", "callback_data": f"discard:{post_id}:{row_id}"})

    return [row] if row else []


# ─── Comandos ─────────────────────────────────────────────────────────────────

def cmd_send_release(post_id: int, title: str, summary: str, edit_url: str,
                     cover: str, sheets_row_id: str,
                     ig_image_path: str = "", ig_caption: str = "") -> dict:
    """Envia card de aprovação com imagem, resumo e botões Site/Instagram/Descartar."""
    caption = (
        f"📰 *{_escape(title)}*\n\n"
        f"{_escape(summary)}\n\n"
        f"[Editar rascunho]({edit_url})"
    )

    # Monta botões: Site sempre presente; IG só se tiver imagem
    row = [{"text": "✅ Site", "callback_data": f"publish:{post_id}:{sheets_row_id}"}]
    if ig_image_path:
        row.append({"text": "📸 Instagram", "callback_data": f"publish_ig:{post_id}:{sheets_row_id}"})
    row.append({"text": "🗑 Descartar", "callback_data": f"discard:{post_id}:{sheets_row_id}"})
    keyboard = {"inline_keyboard": [row]}

    cover_path = Path(cover)
    if cover_path.exists():
        with cover_path.open("rb") as f:
            result = _api(
                "sendPhoto",
                data={
                    "chat_id": _chat_id(),
                    "caption": caption,
                    "parse_mode": "MarkdownV2",
                    "reply_markup": json.dumps(keyboard),
                },
                files={"photo": f},
            )
    else:
        result = _api(
            "sendMessage",
            json={
                "chat_id": _chat_id(),
                "text": caption,
                "parse_mode": "MarkdownV2",
                "reply_markup": keyboard,
                "disable_web_page_preview": False,
            },
        )

    if result.get("ok"):
        msg_id = result["result"]["message_id"]
        # Registra aprovação pendente com schema estendido
        pending = _load_pending()
        pending[str(msg_id)] = {
            "post_id": post_id,
            "sheets_row_id": sheets_row_id,
            "title": title,
            "ig_image_path": ig_image_path,
            "ig_caption": ig_caption,
            "published_site": False,
            "published_ig": False,
        }
        _save_pending(pending)
        print(f"Card enviado. message_id={msg_id}", file=sys.stderr)
        return {"ok": True, "message_id": msg_id}
    else:
        return {"ok": False, "error": result}


def cmd_send_text(message: str) -> dict:
    """Envia mensagem de texto simples."""
    result = _api(
        "sendMessage",
        json={
            "chat_id": _chat_id(),
            "text": message,
            "parse_mode": "HTML",
        },
    )
    return {"ok": result.get("ok"), "message_id": result.get("result", {}).get("message_id")}


def _load_pending_pautas() -> dict:
    if PENDING_PAUTAS_FILE.exists():
        return json.loads(PENDING_PAUTAS_FILE.read_text(encoding="utf-8"))
    return {}


def _save_pending_pautas(data: dict) -> None:
    PENDING_PAUTAS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_PAUTAS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_send_pauta_list(pautas: list[dict]) -> dict:
    """
    Envia lista de sugestões de pauta com botões [Produzir N].

    pautas: lista de dicts com campos: pauta_id, numero, titulo
    Exemplo:
        [{"pauta_id": "3", "numero": 1, "titulo": "O que fazer em Americana..."}, ...]
    """
    # Monta texto da mensagem
    lines = ["📋 *Pautas da semana — escolha para produzir:*\n"]
    for p in pautas:
        num = p.get("numero", "?")
        titulo = p.get("titulo", "")
        lines.append(f"{num}\\. {_escape(titulo)}")
    text = "\n".join(lines)

    # Monta teclado inline em fileiras de 5
    buttons = [
        {"text": f"Produzir {p.get('numero', i+1)}", "callback_data": f"produce:{p['pauta_id']}"}
        for i, p in enumerate(pautas)
    ]
    rows = [buttons[i:i+5] for i in range(0, len(buttons), 5)]
    keyboard = {"inline_keyboard": rows}

    result = _api(
        "sendMessage",
        json={
            "chat_id": _chat_id(),
            "text": text,
            "parse_mode": "MarkdownV2",
            "reply_markup": keyboard,
        },
    )

    if result.get("ok"):
        msg_id = result["result"]["message_id"]
        # Registra mapeamento msg_id → lista de pautas
        pending = _load_pending_pautas()
        pending[str(msg_id)] = [
            {"pauta_id": p["pauta_id"], "numero": p.get("numero", i+1), "titulo": p.get("titulo", "")}
            for i, p in enumerate(pautas)
        ]
        _save_pending_pautas(pending)
        print(f"Lista de pautas enviada. message_id={msg_id}", file=sys.stderr)
        return {"ok": True, "message_id": msg_id}
    else:
        return {"ok": False, "error": result}


def cmd_listen(timeout_secs: int = 1800) -> dict:
    """
    Polling de callbacks por até `timeout_secs` segundos.
    Só processa callbacks cujo message_id esteja em pending_approvals.json —
    isso evita processar cliques velhos de cards anteriores sem descartar cliques novos.
    """
    deadline = time.time() + timeout_secs
    offset = _get_offset()
    processed = []
    seen_update_ids: set[int] = set()  # deduplicação

    print(f"Aguardando aprovações por até {timeout_secs}s...", file=sys.stderr)

    while time.time() < deadline:
        remaining = int(deadline - time.time())
        poll_timeout = min(30, remaining)
        if poll_timeout <= 0:
            break

        result = _api(
            "getUpdates",
            poll_timeout=poll_timeout,
            json={"offset": offset, "timeout": poll_timeout, "allowed_updates": ["callback_query"]},
        )

        if not result.get("ok"):
            time.sleep(5)
            continue

        updates = result.get("result", [])
        for update in updates:
            update_id = update["update_id"]
            offset = update_id + 1
            _save_offset(offset)

            # Deduplicação — ignora se já processamos este update
            if update_id in seen_update_ids:
                continue
            seen_update_ids.add(update_id)

            cb = update.get("callback_query")
            if not cb:
                continue

            data = cb.get("data", "")
            parts = data.split(":")
            if len(parts) != 3:
                continue

            action, post_id, sheets_row_id = parts[0], int(parts[1]), parts[2]
            cb_id = cb["id"]
            msg_id = str(cb["message"]["message_id"])
            user = cb["from"].get("first_name", "alguém")

            # Só processa se este card está na lista de pendentes
            pending = _load_pending()
            if msg_id not in pending:
                print(f"Callback ignorado: msg_id={msg_id} não está nos pendentes.", file=sys.stderr)
                continue

            entry = pending[msg_id]

            # Responde o Telegram ANTES de executar a ação (janela de 60s)
            feedback_map = {
                "publish": "✅ Publicando no site...",
                "publish_ig": "📸 Postando no Instagram...",
                "discard": "🗑 Descartando...",
            }
            feedback_text = feedback_map.get(action, "Processando...")
            try:
                _api("answerCallbackQuery", json={"callback_query_id": cb_id,
                                                   "text": feedback_text})
            except Exception:
                pass

            result_action = _execute_action(
                action, post_id, sheets_row_id, user,
                ig_image_path=entry.get("ig_image_path", ""),
                ig_caption=entry.get("ig_caption", ""),
            )
            processed.append(result_action)

            if action == "discard":
                # Remove todos os botões e o pending
                _api("editMessageReplyMarkup", json={
                    "chat_id": _chat_id(),
                    "message_id": int(msg_id),
                    "reply_markup": json.dumps({"inline_keyboard": []}),
                })
                pending = _load_pending()
                pending.pop(msg_id, None)
                _save_pending(pending)
            else:
                # Atualiza flag e reconstrói teclado sem o botão clicado
                pending = _load_pending()
                if msg_id in pending:
                    if action == "publish":
                        pending[msg_id]["published_site"] = True
                    elif action == "publish_ig":
                        pending[msg_id]["published_ig"] = True

                    remaining_buttons = _build_remaining_buttons(pending[msg_id])
                    _api("editMessageReplyMarkup", json={
                        "chat_id": _chat_id(),
                        "message_id": int(msg_id),
                        "reply_markup": json.dumps({"inline_keyboard": remaining_buttons}),
                    })

                    if not remaining_buttons:
                        pending.pop(msg_id, None)
                    _save_pending(pending)

        # Se não há mais pendentes, encerra
        if not _load_pending():
            print("Sem aprovações pendentes. Encerrando.", file=sys.stderr)
            break

    return {"processed": processed}


def _execute_action(action: str, post_id: int, sheets_row_id: str, user: str,
                    ig_image_path: str = "", ig_caption: str = "") -> dict:
    """Executa Publicar (site), Publicar IG ou Descartar e atualiza o Sheets."""
    import subprocess
    script_dir = Path(__file__).parent

    if action == "publish":
        wp_result = subprocess.run(
            ["python3", str(script_dir / "wp_publish.py"), "publish", "--post-id", str(post_id)],
            capture_output=True, text=True,
        )
        wp_data = json.loads(wp_result.stdout) if wp_result.returncode == 0 else {}
        new_status = "Publicado"
        url = wp_data.get("url", "")
        cmd_send_text(f"✅ <b>Publicado!</b>\n{url}" if url else f"✅ Post #{post_id} publicado.")

        # Atualiza Sheets
        subprocess.run(
            ["python3", str(script_dir / "sheets_write.py"), "update-status",
             "--tab", "Log Releases", "--row-id", sheets_row_id, "--status", new_status],
            capture_output=True,
        )

    elif action == "publish_ig":
        # Apenas marca como Aprovado na planilha — o usuário posta manualmente
        new_status = "Aprovado"
        subprocess.run(
            ["python3", str(script_dir / "sheets_write.py"), "update-status",
             "--tab", "Legendas IG", "--row-id", str(post_id), "--status", new_status],
            capture_output=True,
        )
        cmd_send_text(f"📸 Post #{post_id} aprovado para Instagram. Confira a planilha Legendas IG.")

    else:  # discard
        subprocess.run(
            ["python3", str(script_dir / "wp_publish.py"), "trash", "--post-id", str(post_id)],
            capture_output=True, text=True,
        )
        new_status = "Descartado"
        cmd_send_text(f"🗑 Post #{post_id} descartado por {user}.")

        # Atualiza Sheets
        subprocess.run(
            ["python3", str(script_dir / "sheets_write.py"), "update-status",
             "--tab", "Log Releases", "--row-id", sheets_row_id, "--status", new_status],
            capture_output=True,
        )

    return {"post_id": post_id, "action": action, "status": new_status}


# ─── Offset helper (persiste o offset do getUpdates) ─────────────────────────

OFFSET_FILE = Path(".tmp/telegram_offset.json")

def _get_offset() -> int:
    if OFFSET_FILE.exists():
        return json.loads(OFFSET_FILE.read_text()).get("offset", 0)
    return 0

def _save_offset(offset: int) -> None:
    OFFSET_FILE.parent.mkdir(parents=True, exist_ok=True)
    OFFSET_FILE.write_text(json.dumps({"offset": offset}))


# ─── Markdown V2 escape ───────────────────────────────────────────────────────

def _escape(text: str) -> str:
    """Escapa caracteres especiais do MarkdownV2 do Telegram."""
    special = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in text)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Notificações Telegram com aprovação inline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_sr = subparsers.add_parser("send-release", help="Envia card de aprovação de release")
    p_sr.add_argument("--post-id", type=int, required=True)
    p_sr.add_argument("--title", required=True)
    p_sr.add_argument("--summary", required=True)
    p_sr.add_argument("--edit-url", required=True)
    p_sr.add_argument("--cover", required=True)
    p_sr.add_argument("--sheets-row-id", required=True)
    p_sr.add_argument("--ig-image", default="", help="Caminho da imagem IG (opcional)")
    p_sr.add_argument("--ig-caption", default="", help="Legenda IG (opcional)")
    p_sr.add_argument("--listen", action="store_true",
                       help="Inicia listener imediatamente após enviar (recomendado)")
    p_sr.add_argument("--listen-timeout", type=int, default=1800,
                       help="Tempo de escuta em segundos quando --listen ativado (padrão: 1800)")

    p_spl = subparsers.add_parser("send-pauta-list", help="Envia lista de pautas com botões Produzir")
    p_spl.add_argument("--data", required=True,
                        help='JSON array: [{"pauta_id":"3","numero":1,"titulo":"..."}]')

    p_st = subparsers.add_parser("send-text", help="Envia mensagem de texto")
    p_st.add_argument("--message", required=True)

    p_ls = subparsers.add_parser("listen", help="Processa callbacks pendentes")
    p_ls.add_argument("--timeout", type=int, default=1800,
                       help="Tempo máximo de espera em segundos (padrão: 1800 = 30min)")

    args = parser.parse_args()

    if args.command == "send-pauta-list":
        result = cmd_send_pauta_list(json.loads(args.data))
    elif args.command == "send-release":
        result = cmd_send_release(
            args.post_id, args.title, args.summary,
            args.edit_url, args.cover, args.sheets_row_id,
            ig_image_path=args.ig_image,
            ig_caption=args.ig_caption,
        )
        # Inicia listener imediatamente no mesmo processo se --listen passado
        if args.listen and result.get("ok"):
            sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
            sys.stdout.buffer.write(b"\n")
            result = cmd_listen(args.listen_timeout)
    elif args.command == "send-text":
        result = cmd_send_text(args.message)
    elif args.command == "listen":
        result = cmd_listen(args.timeout)

    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
