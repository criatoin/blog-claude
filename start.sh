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

# ── Instala crontab ────────────────────────────────────────────────────────
crontab /app/crontab

# ── Inicia o cron daemon em background ────────────────────────────────────
cron

# ── Inicia o bot Telegram em foreground (mantém o container vivo) ──────────
exec python /app/execution/telegram_bot.py
