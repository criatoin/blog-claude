# Deploy no Coolify — +blog autônomo

## Pré-requisitos
- Repositório no GitHub com o projeto
- Servidor Coolify apontando para esse repo
- Arquivo `.env` local com todas as variáveis

---

## Passo 1 — Gerar os tokens em base64 (rodar uma vez, localmente)

```bash
# No terminal, dentro da pasta do projeto:
base64 -w0 token.json       # → copia o output → GMAIL_TOKEN_B64
base64 -w0 token_sheets.json  # → copia o output → SHEETS_TOKEN_B64
```

> **Windows (PowerShell):**
> ```powershell
> [Convert]::ToBase64String([IO.File]::ReadAllBytes("token.json"))
> [Convert]::ToBase64String([IO.File]::ReadAllBytes("token_sheets.json"))
> ```

---

## Passo 2 — Criar projeto no Coolify

1. Painel → **Projects** → **New Project** → nome: `+blog`
2. **New Resource** → **Docker Compose** → conectar ao repositório GitHub
3. Selecionar branch: `main`

---

## Passo 3 — Configurar variáveis de ambiente no Coolify

No painel → **Environment Variables** → adicionar **todas** as variáveis abaixo:

```
# API Keys
OPENROUTER_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TAVILY_API_KEY=
UNSPLASH_ACCESS_KEY=       (opcional)
GEMINI_API_KEY=            (opcional)

# WordPress
WP_URL=
WP_USER=
WP_APP_PASSWORD=

# Google Sheets
SHEETS_ID=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REFRESH_TOKEN=

# Gmail OAuth
GMAIL_CLIENT_ID=
GMAIL_CLIENT_SECRET=
GMAIL_REFRESH_TOKEN=

# Tokens OAuth (base64 — gerados no Passo 1)
GMAIL_TOKEN_B64=<output do base64 token.json>
SHEETS_TOKEN_B64=<output do base64 token_sheets.json>
```

---

## Passo 4 — Deploy

1. Coolify → **Deploy** → aguardar build (~3-5 min)
2. Logs do `telegram-bot` devem exibir:
   ```
   [start] token.json reconstituído de GMAIL_TOKEN_B64
   [start] token_sheets.json reconstituído de SHEETS_TOKEN_B64
   [bot] Telegram bot daemon iniciado
   ```
3. Cron jobs internos ao container:
   - Releases: todo dia útil, toda hora (guard no script: 8h-18h)
   - Pauta: toda segunda às 9h

---

## Passo 5 — Validação

Enviar via Telegram para o bot:
```
/status
```
Ou aguardar o próximo horário de execução e verificar os logs.

---

## Renovação de tokens OAuth

Os tokens Google expiram periodicamente. Quando isso acontecer:
1. Rodar localmente: `python execution/gmail_fetch.py` (ou o script que usa o token)
2. O token será renovado automaticamente no arquivo local
3. Repetir o Passo 1 para gerar novo base64
4. Atualizar as variáveis `GMAIL_TOKEN_B64` / `SHEETS_TOKEN_B64` no Coolify
5. Redeploy (ou restart do container)

---

## Estrutura do container

```
start.sh
├── Reconstrói token.json e token_sheets.json (de env vars)
├── Instala crontab interno
├── Sobe cron daemon (background)
└── Sobe telegram_bot.py (foreground — mantém container vivo)
         └── Cron dispara:
               ├── run_releases.py  (toda hora, seg-sex, guard 8h-18h)
               └── run_pauta_generate.py  (toda segunda 9h)
```
