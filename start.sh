#!/bin/bash
# start.sh — inicia cron + bot Telegram no mesmo container

# Instala crontab
crontab /app/crontab

# Inicia o cron daemon em background
cron

# Inicia o bot Telegram em foreground (mantém o container vivo)
exec python /app/execution/telegram_bot.py
