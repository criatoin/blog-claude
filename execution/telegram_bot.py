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


def _execute_action(action: str, post_id: int, sheets_row_id: str, user: str,
                    ig_image_path: str = "", ig_caption: str = "") -> dict:
    """
    Executa Publicar (site), Publicar IG ou Descartar.
    Delega para _execute_action de telegram_notify.
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    from telegram_notify import _execute_action as _notify_execute
    return _notify_execute(action, post_id, sheets_row_id, user,
                           ig_image_path=ig_image_path, ig_caption=ig_caption)


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
    Captura callbacks publish:id:row / publish_ig:id:row / discard:id:row.
    Só processa se msg_id estiver nos pendentes.
    Suporta ações parciais: botões clicados somem, restantes permanecem.
    """
    pending = _load_json(PENDING_FILE)
    if msg_id not in pending:
        print(f"[bot] Callback ignorado: msg_id={msg_id} não está nos pendentes.", file=sys.stderr)
        _api("answerCallbackQuery", json={"callback_query_id": cb_id, "text": "Este card já foi processado."})
        return

    entry = pending[msg_id]

    # Responde ao Telegram antes de executar
    feedback_map = {
        "publish": "✅ Publicando no site...",
        "publish_ig": "📸 Postando no Instagram...",
        "discard": "🗑 Descartando...",
    }
    feedback = feedback_map.get(action, "Processando...")
    _api("answerCallbackQuery", json={"callback_query_id": cb_id, "text": feedback})

    # Executa ação
    _execute_action(action, post_id, sheets_row_id, user,
                    ig_image_path=entry.get("ig_image_path", ""),
                    ig_caption=entry.get("ig_caption", ""))

    if action == "discard":
        # Remove todos os botões e o pending
        _api("editMessageReplyMarkup", json={
            "chat_id": _chat_id(),
            "message_id": int(msg_id),
            "reply_markup": json.dumps({"inline_keyboard": []}),
        })
        pending = _load_json(PENDING_FILE)
        pending.pop(msg_id, None)
        _save_json(PENDING_FILE, pending)
    else:
        # Atualiza flag e reconstrói teclado sem o botão clicado
        pending = _load_json(PENDING_FILE)
        if msg_id in pending:
            if action == "publish":
                pending[msg_id]["published_site"] = True
            elif action == "publish_ig":
                pending[msg_id]["published_ig"] = True

            sys.path.insert(0, str(SCRIPT_DIR))
            from telegram_notify import _build_remaining_buttons
            remaining = _build_remaining_buttons(pending[msg_id])

            _api("editMessageReplyMarkup", json={
                "chat_id": _chat_id(),
                "message_id": int(msg_id),
                "reply_markup": json.dumps({"inline_keyboard": remaining}),
            })

            if not remaining:
                pending.pop(msg_id, None)
            _save_json(PENDING_FILE, pending)


def _completar_com_imagem(entry: dict, raw_image_path: str) -> None:
    """
    Fecha uma pendência de imagem: processa a foto, define destacada no WP,
    gera arte IG e envia o card de aprovação completo.
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    slug = entry["slug"]
    post_id = entry["post_id"]
    output_dir = str(PROJECT_DIR / ".tmp")

    def _run_json_local(args: list[str]) -> dict | None:
        result = subprocess.run(["python3"] + args, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", cwd=str(PROJECT_DIR))
        if result.returncode != 0:
            print(f"[bot] Erro em {Path(args[0]).name}: {result.stderr[:300]}", file=sys.stderr)
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return None

    # 1. Processa para capa 1920x1080 WebP
    proc = _run_json_local([str(SCRIPT_DIR / "image_process.py"),
                            "--input", raw_image_path, "--slug", slug,
                            "--output-dir", output_dir])
    if not proc or not proc.get("path"):
        _send_text(f"❌ Falha ao processar a imagem do post #{post_id}. Tente outra foto.")
        return
    cover_path = proc["path"]

    # 2. Define imagem destacada no WP
    _run_json_local([str(SCRIPT_DIR / "wp_publish.py"), "set-featured",
                     "--post-id", str(post_id), "--image-path", cover_path])

    # 3. Gera arte IG e sobe para o WP Media
    ig_path = ""
    ig_result = _run_json_local([
        str(SCRIPT_DIR / "instagram_image.py"),
        "--cover", cover_path, "--slug", slug,
        "--title", entry.get("titulo", ""),
        "--category", entry.get("category_name", "Eventos"),
        "--art-title", entry.get("art_title", ""),
        "--art-subtitle", entry.get("art_subtitle", ""),
        "--output-dir", output_dir,
    ])
    if ig_result:
        ig_path = ig_result.get("path", "")
        if ig_path:
            _run_json_local([str(SCRIPT_DIR / "wp_publish.py"), "upload-image",
                             "--image-path", ig_path,
                             "--title", f"{entry.get('titulo', '')} — Instagram"])

    # 4. Envia o card de aprovação completo
    notify_args = [str(SCRIPT_DIR / "telegram_notify.py"), "send-release",
                   "--post-id", str(post_id),
                   "--title", entry.get("titulo", ""),
                   "--summary", entry.get("summary", ""),
                   "--edit-url", entry.get("edit_url", ""),
                   "--cover", cover_path,
                   "--sheets-row-id", "0"]
    if entry.get("card_meta"):
        notify_args += ["--card-meta", json.dumps(entry["card_meta"], ensure_ascii=False)]
    if ig_path:
        notify_args += ["--ig-image", ig_path, "--ig-caption", entry.get("legenda_curta", "")]
    subprocess.run(["python3"] + notify_args, cwd=str(PROJECT_DIR))
    print(f"[bot] Pendência de imagem do post #{post_id} resolvida.", file=sys.stderr)


def _handle_image_callback(action: str, post_id_str: str, cb_id: str, msg_id: str) -> None:
    """Callbacks usethis:<post_id> e sendphoto:<post_id>."""
    sys.path.insert(0, str(SCRIPT_DIR))
    from telegram_notify import _load_pending_images, _save_pending_images

    state = _load_pending_images()
    entry = state["cards"].get(msg_id)
    if not entry or str(entry.get("post_id")) != post_id_str:
        _api("answerCallbackQuery", json={"callback_query_id": cb_id,
                                          "text": "Este card já foi processado."})
        return

    if action == "usethis":
        _api("answerCallbackQuery", json={"callback_query_id": cb_id,
                                          "text": "✔️ Usando a sugestão..."})
        _api("editMessageReplyMarkup", json={
            "chat_id": _chat_id(), "message_id": int(msg_id),
            "reply_markup": json.dumps({"inline_keyboard": []})})
        state["cards"].pop(msg_id, None)
        _save_pending_images(state)
        _completar_com_imagem(entry, entry.get("suggestion_path", ""))

    elif action == "sendphoto":
        _api("answerCallbackQuery", json={"callback_query_id": cb_id,
                                          "text": "📷 Manda a foto aqui no chat."})
        state["awaiting"] = {"post_id": entry["post_id"], "msg_id": msg_id}
        _save_pending_images(state)
        _send_text(f"📷 Aguardando foto para o post #{entry['post_id']} — envie como imagem aqui no chat.")


def _handle_photo_message(message: dict) -> None:
    """Foto recebida no chat: se há pendência aguardando, resolve com ela."""
    sys.path.insert(0, str(SCRIPT_DIR))
    from telegram_notify import _load_pending_images, _save_pending_images

    state = _load_pending_images()
    awaiting = state.get("awaiting")
    if not awaiting:
        return  # foto sem pendência ativa — ignora

    photos = message.get("photo", [])
    if not photos:
        return
    file_id = photos[-1]["file_id"]  # maior resolução

    # Baixa o arquivo do Telegram
    info = _api("getFile", json={"file_id": file_id})
    file_path = info.get("result", {}).get("file_path", "")
    if not file_path:
        _send_text("❌ Não consegui baixar a foto. Tente novamente.")
        return
    url = f"https://api.telegram.org/file/bot{_token()}/{file_path}"
    resp = requests.get(url, timeout=60)

    msg_id = awaiting["msg_id"]
    entry = state["cards"].get(msg_id)
    if not entry:
        state["awaiting"] = None
        _save_pending_images(state)
        return

    raw_path = PROJECT_DIR / ".tmp" / f"{entry['slug']}_telegram.jpg"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(resp.content)

    # Limpa a pendência antes de completar (evita reuso duplo)
    state["cards"].pop(msg_id, None)
    state["awaiting"] = None
    _save_pending_images(state)
    _api("editMessageReplyMarkup", json={
        "chat_id": _chat_id(), "message_id": int(msg_id),
        "reply_markup": json.dumps({"inline_keyboard": []})})

    _send_text(f"✅ Foto recebida! Processando o post #{entry['post_id']}...")
    _completar_com_imagem(entry, str(raw_path))


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
                    "allowed_updates": ["callback_query", "message"],
                },
            )

            if not result.get("ok"):
                error_code = result.get("error_code", 0)
                if error_code == 409:
                    print("[bot] 409 Conflict — removendo webhook e aguardando 30s...", file=sys.stderr)
                    _api("deleteWebhook", json={"drop_pending_updates": False})
                    time.sleep(30)
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

                msg = update.get("message")
                if msg and msg.get("photo"):
                    _handle_photo_message(msg)
                    continue

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

                elif data_str.startswith(("usethis:", "sendphoto:")):
                    action, pid = data_str.split(":", 1)
                    _handle_image_callback(action, pid, cb_id, msg_id)

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
