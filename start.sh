#!/bin/bash
# start.sh — inicia cron + bot Telegram no mesmo container

# ── Reconstrói tokens OAuth a partir de variáveis de ambiente ─────────────
# No Coolify: adicionar GMAIL_TOKEN_B64 e SHEETS_TOKEN_B64 como env vars
# Geração local: base64 -w0 token.json && base64 -w0 token_sheets.json
if [ -n "$GMAIL_TOKEN_B64" ]; then
    echo "$GMAIL_TOKEN_B64" | base64 -d > /app/token.json
    echo "[start] token.json reconstituído de GMAIL_TOKEN_B64"
fi

if [ -n "$SHEETS_TOKEN_B64" ]; then
    echo "$SHEETS_TOKEN_B64" | base64 -d > /app/token_sheets.json
    echo "[start] token_sheets.json reconstituído de SHEETS_TOKEN_B64"
fi

# ── Exporta env vars para .env (cron não herda variáveis do container) ────
printenv | grep -v "^_=" | grep -v "^SHLVL=" | grep -v "^PWD=" > /app/.env
echo "[start] .env gerado com $(wc -l < /app/.env) variáveis para o cron"

# ── Instala crontab ────────────────────────────────────────────────────────
crontab /app/crontab

# ── Inicia o cron daemon em background ────────────────────────────────────
cron

# ── Limpa webhook antes de iniciar (evita 409 de containers anteriores) ────
python3 -c "
import os, requests, time
token = os.getenv('TELEGRAM_BOT_TOKEN','')
if token:
    requests.post(f'https://api.telegram.org/bot{token}/deleteWebhook',
                  json={'drop_pending_updates': False}, timeout=10)
    print('[start] deleteWebhook executado')
    time.sleep(5)
"

# ── Inicia o bot Telegram em foreground (mantém o container vivo) ──────────
exec python3 /app/execution/telegram_bot.py
