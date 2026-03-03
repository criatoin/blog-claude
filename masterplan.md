# Masterplan — Sistema Autônomo +blog

> Documento de referência da arquitetura atual.
> Atualizado em: 2026-03-03
> Arquitetura: CLAUDE.md (3 camadas: Diretiva → Orquestração → Execução)

---

## Contexto

**Projeto:** Sistema de automação editorial do +blog — portal de cultura e diversão de Americana,
Santa Bárbara d'Oeste, Nova Odessa e Sumaré.
**Status:** Sistema autônomo implementado. Fase atual: deploy no Coolify.
**Time:** 2 pessoas. Aprovação humana obrigatória antes de publicar.

---

## Arquitetura de Pastas

```
+blog claude/
├── CLAUDE.md                        ← skill base (não modificar)
├── masterplan.md                    ← este arquivo
├── requirements.txt                 ← dependências Python
├── Dockerfile                       ← imagem Python 3.12-slim
├── docker-compose.yml               ← 3 serviços: telegram-bot, run-releases, run-pauta
├── .dockerignore                    ← exclui .env, .tmp, token.json, __pycache__
├── .gitignore                       ← exclui .env, tokens, .tmp
├── setup_scheduler.bat              ← Task Scheduler Windows (fase 1)
├── setup_google_auth.py             ← gera token OAuth Google (rodar localmente)
├── agents/
│   ├── master.md                    ← roteador de comandos
│   ├── release-agent.md             ← fluxo: email → rascunho + aprovação
│   └── pauta-agent.md               ← fluxo: dados → pauta → produção + aprovação
├── directives/
│   ├── release-to-post.md           ← SOP de reescrita no tom +blog
│   ├── image-select-resize.md       ← SOP de seleção e tratamento de imagem
│   ├── social-instagram.md          ← SOP de legenda e arte para Instagram
│   └── pauta-semanal.md             ← SOP de geração e produção de pautas
├── execution/
│   ├── llm_call.py                  ← wrapper OpenRouter/DeepSeek (llm_call, llm_call_json)
│   ├── gmail_fetch.py               ← busca emails não lidos + salva anexos
│   ├── wp_publish.py                ← cria rascunho / publica / vincula imagem
│   ├── image_select.py              ← score e seleção de melhor imagem entre anexos
│   ├── image_process.py             ← resize cover 1920×1080 + WebP <1MB
│   ├── image_generate.py            ← Unsplash → Gemini → fallback
│   ├── instagram_image.py           ← arte IG 1:1 com modelos de referência
│   ├── sheets_write.py              ← escreve pautas, legendas e log no Sheets (retorna row_id)
│   ├── sheets_read.py               ← lê pautas e fila de legendas do Sheets
│   ├── telegram_notify.py           ← envia notificações + botões inline
│   ├── telegram_bot.py              ← daemon long polling (callbacks de aprovação/produção)
│   ├── search_sources.py            ← Tavily: pesquisa fontes para pautas
│   ├── gsc_report.py                ← Google Search Console: queries com gap de CTR
│   ├── ga_report.py                 ← Google Analytics 4: posts mais visitados (30d)
│   ├── run_releases.py              ← pipeline completo: email → rascunho WP → Telegram
│   ├── run_pauta_generate.py        ← gera 10 pautas semanais → Telegram
│   └── run_pauta_produce.py         ← produz pauta individual (--pauta-id N)
├── assets/
│   └── instagram/
│       ├── 6.jpg                    ← modelo de referência IG
│       └── 8.jpg                    ← modelo de referência IG
└── .tmp/                            ← arquivos intermediários (sempre regeneráveis, nunca commitar)
    ├── pending_approvals.json       ← cards aguardando [Publicar]/[Descartar]
    ├── pending_pautas.json          ← listas de pauta aguardando [Produzir N]
    └── telegram_offset.json         ← offset do getUpdates (deduplicação)
```

---

## Scripts de Execução — Interfaces

### `llm_call.py`
- **Função:** Wrapper OpenRouter (DeepSeek como modelo padrão)
- **Entrada (CLI):** `--prompt "texto"` `--system "sistema"` `--json` `--model "id"`
- **Saída:** texto plano ou JSON validado

### `gmail_fetch.py`
- **Função:** Busca emails não lidos + salva anexos em `.tmp/`
- **Saída JSON:** `[{id, assunto, de, data, corpo, anexos: [{path, tipo}]}]`
- **Auth:** token.json (OAuth Gmail)

### `wp_publish.py`
- **Função:** Criar rascunho, publicar, mover para lixeira, vincular imagem destacada
- **Comandos:** `--cmd draft` `--cmd publish` `--cmd trash` `--cmd attach-image`
- **Saída JSON:** `{ok, post_id, link}`

### `image_select.py`
- **Função:** Score de imagens por resolução + proporção 16:9 + qualidade
- **Entrada:** lista de paths `.tmp/`
- **Saída JSON:** `{ok, path, score}` ou `{ok: false, reason}`

### `image_process.py`
- **Função:** Resize + crop 1920×1080 + converte para WebP <1MB
- **Entrada:** `--input path` `--output path`
- **Saída JSON:** `{ok, path, size_kb}`

### `image_generate.py`
- **Função:** Gera imagem via Unsplash (grátis) → Gemini (fallback)
- **Entrada:** `--query "texto"` `--output path`
- **Saída JSON:** `{ok, path, fonte}`

### `instagram_image.py`
- **Função:** Arte Instagram 1:1 com modelo de referência
- **Entrada:** `--cover path` `--modelo path` `--output path`
- **Saída JSON:** `{ok, path}`

### `sheets_write.py`
- **Função:** Escreve pautas, legendas, log de releases no Sheets
- **Comandos:** `--cmd log-release` `--cmd pauta` `--cmd legenda-ig`
- **Saída JSON:** `{ok, row_id}` (row_id usado pelo telegram_bot para callbacks)

### `sheets_read.py`
- **Função:** Lê pautas e legendas do Sheets
- **Comandos:** `--cmd pautas-pendentes` `--cmd pauta --id N`
- **Saída JSON:** lista de pautas ou pauta individual

### `telegram_notify.py`
- **Função:** Envia card com preview + botões inline [Publicar]/[Descartar] ou [Produzir N]
- **Comandos:** `--cmd release` `--cmd pauta`
- **Saída JSON:** `{ok, message_id}`

### `telegram_bot.py`
- **Função:** Daemon long polling — intercepta callbacks dos botões e executa ações
- **Callbacks:**
  - `publish:post_id:row_id` → wp publish + Sheets: Publicado
  - `discard:post_id:row_id` → wp trash + Sheets: Descartado
  - `produce:pauta_id` → subprocess.Popen(run_pauta_produce.py)
- **Estado:** `.tmp/pending_approvals.json`, `.tmp/telegram_offset.json`

### `search_sources.py`
- **Função:** Pesquisa fontes via Tavily API
- **Entrada:** `--query "texto"` `--n 5`
- **Saída JSON:** `[{titulo, url, trecho}]`

### `gsc_report.py`
- **Função:** Top queries com impressões > 50 e CTR < 3%
- **Saída JSON:** `[{query, impressions, ctr, clicks}]`

### `ga_report.py`
- **Função:** Top 10 posts mais visitados (últimos 30 dias)
- **Saída JSON:** `[{titulo, url, sessions}]`

### `run_releases.py`
- **Função:** Pipeline completo — email → rascunho WP → notificação Telegram
- **Roda a cada hora** (cron / Task Scheduler)
- **Chama:** gmail_fetch → llm_call (relevância + reescrita) → image_select/process/generate → wp_publish → sheets_write → telegram_notify

### `run_pauta_generate.py`
- **Função:** Gera 10 pautas semanais → envia lista ao Telegram
- **Roda toda segunda às 9h** (cron)
- **Chama:** gsc_report → ga_report → llm_call → sheets_write → telegram_notify

### `run_pauta_produce.py`
- **Função:** Produz pauta individual completa (post + imagem + IG)
- **Entrada:** `--pauta-id N`
- **Chama:** sheets_read → search_sources → llm_call → image_generate → instagram_image → wp_publish → sheets_write → telegram_notify

---

## Variáveis de Ambiente (.env)

```env
# LLM (OpenRouter)
OPENROUTER_API_KEY=

# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# WordPress
WP_URL=https://maisblog.com.br
WP_USER=
WP_APP_PASSWORD=

# Google Sheets (OAuth)
SHEETS_ID=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REFRESH_TOKEN=

# Gmail (OAuth)
GMAIL_CLIENT_ID=
GMAIL_CLIENT_SECRET=
GMAIL_REFRESH_TOKEN=

# Pesquisa
TAVILY_API_KEY=

# Imagem
UNSPLASH_ACCESS_KEY=
GEMINI_API_KEY=

# Google Analytics / Search Console
GA4_PROPERTY_ID=
GSC_SITE_URL=
```

---

## Google Sheets — Estrutura da Planilha Central

**Nome:** `Operação +blog`

### Aba 1 — Pautas

| id | titulo | keyword | categoria | justificativa | status | slug_sugerido | link_post |
|----|--------|---------|-----------|---------------|--------|---------------|-----------|

**Status:** `Pendente` / `Produzindo` / `Produzido` / `Publicado` / `Sem fontes` / `Descartado`

### Aba 2 — Legendas IG

| id_post | titulo | legenda | hashtags | status | data_postagem | path_imagem |
|---------|--------|---------|----------|--------|---------------|-------------|

**Status:** `Pronta` / `Postada` / `Arquivada`

### Aba 3 — Log Releases

| id | origem_email | assunto | data_recebimento | relevante | status | link_post | motivo_descarte |
|----|--------------|---------|------------------|-----------|--------|-----------|-----------------|

---

## Fluxo de Callbacks Telegram

```
Usuário clica [Publicar]
  → telegram_bot.py recebe callback "publish:post_id:row_id"
  → wp_publish.py --cmd publish --post-id POST_ID
  → sheets_write.py --cmd update-status --row ROW_ID --status Publicado
  → telegram_bot.py edita mensagem: "✅ Publicado"

Usuário clica [Descartar]
  → telegram_bot.py recebe callback "discard:post_id:row_id"
  → wp_publish.py --cmd trash --post-id POST_ID
  → sheets_write.py --cmd update-status --row ROW_ID --status Descartado
  → telegram_bot.py edita mensagem: "🗑 Descartado"

Usuário clica [Produzir N]
  → telegram_bot.py recebe callback "produce:pauta_id"
  → subprocess.Popen(["python", "execution/run_pauta_produce.py", "--pauta-id", N])
  → run_pauta_produce.py roda em background → envia novo card de aprovação
```

---

## Docker — Infraestrutura

### Serviços

| Serviço | Comando | Restart | Tipo no Coolify |
|---------|---------|---------|-----------------|
| `telegram-bot` | `python execution/telegram_bot.py` | `always` | Long-running service |
| `run-releases` | `python execution/run_releases.py` | — | Cron Job: `0 8-18 * * 1-5` |
| `run-pauta` | `python execution/run_pauta_generate.py` | — | Cron Job: `0 9 * * 1` |

### Volumes

- **`blog_tmp`** (named volume): compartilhado pelos 3 serviços — `.tmp/` com estado dos callbacks
- **`token.json`** e **`token_sheets.json`**: montados via bind mount do host (nunca na imagem)

### .dockerignore

Exclui da imagem: `.env`, `.git`, `.tmp`, `__pycache__`, `*.pyc`, `.venv`, `token.json`, `token_sheets.json`

---

## Deploy no Coolify — Passo a Passo

### Pré-requisito: repositório GitHub privado

```bash
cd "C:\Users\DANILLO\Desktop\LP's IA\+blog claude"
git init
git add .
git commit -m "feat: sistema autonomo do +blog"
git remote add origin https://github.com/SEU_USER/blog-autonomo.git
git push -u origin main
```

> `.env`, `token.json`, `token_sheets.json` estão no `.gitignore` — não serão commitados.

### Passo 1 — Criar projeto no Coolify

1. Painel → **Projects** → **New Project** → nome: `+blog`
2. **New Resource** → **Docker Compose** → conectar ao repositório GitHub
3. Coolify detecta os 3 serviços no `docker-compose.yml`

### Passo 2 — Configurar variáveis de ambiente

No painel Coolify → **Environment Variables** → adicionar todas as variáveis do `.env`.

### Passo 3 — Upload dos tokens OAuth via SSH

```bash
scp token.json root@SEU_SERVIDOR:/opt/blog-tokens/token.json
scp token_sheets.json root@SEU_SERVIDOR:/opt/blog-tokens/token_sheets.json
```

No `docker-compose.yml` do servidor, ajustar volumes para apontar para `/opt/blog-tokens/`.

### Passo 4 — Configurar serviços no painel

- **telegram-bot:** Long-running service, restart: always
- **run-releases:** Cron Job, schedule: `0 8-18 * * 1-5`
- **run-pauta:** Cron Job, schedule: `0 9 * * 1`

### Passo 5 — Primeiro deploy

1. Coolify → **Deploy** → aguardar build (~3-5min)
2. Logs do `telegram-bot` → deve exibir: `[bot] Telegram bot daemon iniciado`
3. Executar `run-releases` manualmente uma vez para validar

---

## Verificação Local (antes do Coolify)

```bash
# 1. Build da imagem
docker build -t blog-test .

# 2. Testar LLM
docker run --env-file .env blog-test python execution/llm_call.py --prompt "olá"

# 3. Testar pipeline completo com volumes
docker-compose up telegram-bot
```

---

## Custos Estimados por Post

| Item | Custo |
|------|-------|
| Reescrita de texto (DeepSeek via OpenRouter) | ~$0.001 |
| Imagem capa — Unsplash (maioria dos casos) | $0.00 |
| Imagem capa — Gemini (fallback) | ~$0.039 |
| Arte Instagram — Gemini | ~$0.039 |
| Pesquisa de fontes — Tavily (free tier) | $0.00 |
| **Total médio com Unsplash** | **~$0.04** |
| **Total médio sem Unsplash** | **~$0.08** |
