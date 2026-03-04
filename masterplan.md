# Masterplan — Sistema Autônomo +blog

> Documento de referência da arquitetura atual.
> Atualizado em: 2026-03-04
> Arquitetura: CLAUDE.md (3 camadas: Diretiva → Orquestração → Execução)

---

## Contexto

**Projeto:** Sistema de automação editorial do +blog — portal de cultura e diversão de Americana,
Santa Bárbara d'Oeste, Nova Odessa e Sumaré.
**Status:** ✅ PRODUÇÃO — rodando no Coolify (serv2.criatoin.com.br)
**Time:** 2 pessoas. Aprovação humana obrigatória antes de publicar.

---

## Arquitetura de Pastas

```
+blog claude/
├── CLAUDE.md                        ← skill base (não modificar)
├── masterplan.md                    ← este arquivo
├── requirements.txt                 ← dependências Python
├── Dockerfile                       ← imagem Python 3.12-slim
├── docker-compose.yml               ← 1 serviço: telegram-bot (bot + cron interno)
├── start.sh                         ← entrypoint: reconstrói tokens → cron → bot
├── crontab                          ← releases toda hora + pauta toda segunda 9h
├── .dockerignore                    ← exclui .env, .tmp, token.json, __pycache__
├── .gitignore                       ← exclui .env, tokens, .tmp
├── setup_google_auth.py             ← gera token OAuth Google (rodar localmente)
├── directives/
│   ├── release-to-post.md           ← SOP de reescrita no tom +blog
│   ├── image-select-resize.md       ← SOP de seleção e tratamento de imagem
│   ├── social-instagram.md          ← SOP de legenda e arte para Instagram
│   ├── pauta-semanal.md             ← SOP de geração e produção de pautas
│   └── deploy-coolify.md            ← guia de deploy e renovação de tokens
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
- **Auth:** fallback automático → GMAIL_CLIENT_ID + GMAIL_CLIENT_SECRET + GMAIL_REFRESH_TOKEN

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
- **Guard:** roda apenas seg-sex, 8h-18h (datetime.now() no topo do script)
- **Cron:** `0 * * * 1-5` (toda hora, seg-sex — guard interno filtra horário)
- **Chama:** gmail_fetch → llm_call (relevância + reescrita) → image_select/process/generate → wp_publish → sheets_write → telegram_notify

### `run_pauta_generate.py`
- **Função:** Gera 10 pautas semanais → envia lista ao Telegram
- **Cron:** `0 9 * * 1` (toda segunda às 9h)
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

# Tokens OAuth em base64 (opcional — reconstrói token.json no container)
GMAIL_TOKEN_B64=
SHEETS_TOKEN_B64=
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

## Docker — Infraestrutura (PRODUÇÃO)

### Arquitetura atual: 1 serviço único

```
telegram-bot (restart: always)
  └── start.sh
        ├── Reconstrói token.json de GMAIL_TOKEN_B64  (se env var presente)
        ├── Reconstrói token_sheets.json de SHEETS_TOKEN_B64  (se env var presente)
        ├── crontab → cron daemon (background)
        │     ├── 0 * * * 1-5  → run_releases.py  (guard interno: 8h-18h)
        │     └── 0 9 * * 1    → run_pauta_generate.py
        └── telegram_bot.py (foreground — mantém container vivo)
```

### Volumes

- **`blog_tmp`** (named volume): `.tmp/` com estado dos callbacks

### Autenticação Google (sem token.json)

Os scripts têm fallback automático para env vars se `token.json` não existir:
- Gmail: `GMAIL_CLIENT_ID` + `GMAIL_CLIENT_SECRET` + `GMAIL_REFRESH_TOKEN`
- Sheets: `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` + `GOOGLE_REFRESH_TOKEN`

---

## Deploy no Coolify — Configuração Atual

| Campo | Valor |
|-------|-------|
| Coolify URL | https://serv2.criatoin.com.br |
| Projeto | `blog-claude` |
| Serviço | `blog-telegram-bot` |
| Repositório | github.com/criatoin/blog-claude |
| Branch | `main` |
| Status | `running` |

### Redeploy via API (força rebuild do código)

```bash
curl -X POST \
  -H "Authorization: Bearer <COOLIFY_API_TOKEN>" \
  "https://serv2.criatoin.com.br/api/v1/deploy?uuid=ksko44gg48k0wsg04sosscsc&force=true"
```

### Verificar status

```bash
curl -H "Authorization: Bearer <COOLIFY_API_TOKEN>" \
  "https://serv2.criatoin.com.br/api/v1/applications/ksko44gg48k0wsg04sosscsc"
```

---

## Renovação de Tokens OAuth

Quando o Google exigir reautenticação:

1. Localmente: `python setup_google_auth.py`
2. Atualizar env vars no Coolify: `GMAIL_REFRESH_TOKEN` e/ou `GOOGLE_REFRESH_TOKEN`
3. Redeploy (ou restart) do container

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
