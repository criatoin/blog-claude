# Agente Mestre — Roteador de Comandos +blog

## O que fazer com este arquivo
Leia este arquivo PRIMEIRO sempre que receber um comando relacionado ao +blog.
Ele determina qual agente ou ação executar com base no comando do usuário.

---

## Tabela de roteamento

| Comando recebido | Arquivo do agente | Etapa |
|------------------|-------------------|-------|
| `"processe releases"` | `agents/release-agent.md` | Fluxo 1 completo |
| `"gere pauta semanal"` | `agents/pauta-agent.md` (Etapa 2A) | Geração de 10 pautas |
| `"produzir pauta #N"` | `agents/pauta-agent.md` (Etapa 2B) | Produção da pauta N |
| `"listar pautas pendentes"` | ← ver abaixo | Consulta ao Sheets |
| `"listar legendas prontas"` | ← ver abaixo | Consulta ao Sheets |

---

## Consultas rápidas (sem agente)

### Listar pautas pendentes
```bash
python execution/sheets_read.py pautas --status "Pendente"
```
Exibir resultado formatado como lista numerada com: ID, título, keyword, justificativa.

### Listar legendas prontas
```bash
python execution/sheets_read.py legendas --status "Pronta"
```
Exibir resultado com: id_post, título, prévia da legenda (primeiras 80 chars).

---

## Princípios de operação

1. **Leia a diretiva antes de agir** — cada agente aponta para directives/
2. **Nunca invente dados** — se não há informação, sinalize com `[DADO AUSENTE]`
3. **Aprovação humana obrigatória** — toda publicação passa pelo Telegram antes de ir ao ar
4. **Self-annealing** — se um script falhar, corrija e atualize a diretiva com o aprendizado
5. **Intermediários em .tmp/** — nunca persista dados de processo fora do .tmp/ ou Sheets

---

## Contexto do sistema

**Portal:** +blog (cultura e diversão de Americana, SBO, Nova Odessa e Sumaré)
**Stack de scripts:** Python em `execution/`
**Aprovação:** via bot Telegram (botões inline Publicar/Descartar)
**Log central:** Google Sheets "Operação +blog" (ID: ver SHEETS_ID no .env)

---

## Cron jobs recomendados (configurar manualmente)

```
# Processar releases toda hora (dias úteis, horário comercial)
0 8-18 * * 1-5  cd /path/to/+blog-claude && claude "processe releases"

# Gerar pauta toda segunda às 9h
0 9 * * 1       cd /path/to/+blog-claude && claude "gere pauta semanal"
```

> **Nota:** Para rodar como cron, o Claude Code precisa estar disponível no PATH
> e as credenciais (.env, token*.json) devem estar no diretório do projeto.

---

## Variáveis de ambiente obrigatórias

Verifique se todas estão no `.env` antes de rodar qualquer fluxo:

| Variável | Usado por |
|----------|-----------|
| `GMAIL_CLIENT_ID/SECRET/REFRESH_TOKEN` | gmail_fetch.py |
| `WP_URL / WP_USER / WP_APP_PASSWORD` | wp_publish.py |
| `GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN` | sheets_write.py, sheets_read.py |
| `SHEETS_ID` | sheets_write.py, sheets_read.py |
| `TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID` | telegram_notify.py |
| `UNSPLASH_ACCESS_KEY` | image_generate.py |
| `GEMINI_API_KEY` | image_generate.py, instagram_image.py |
| `OPENAI_API_KEY` | image_generate.py (fallback) |
| `TAVILY_API_KEY` | search_sources.py |
| `GSC_SITE_URL` | gsc_report.py |
| `GA4_PROPERTY_ID` | ga_report.py |
