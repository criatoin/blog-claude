# Agente — Pauta Semanal

## Ativação
```bash
claude "gere pauta semanal"
# ou automaticamente via cron toda segunda às 9h
```

---

## Etapa 2A — Geração de pautas

### Passo 1 — Coletar dados do GSC (opcional)

```bash
python execution/gsc_report.py --days 90 --max 20 --min-impressions 30
```

- Retorna queries com alto volume de impressões e CTR < 3%
- **Se falhar por qualquer motivo (auth, rede, etc.):** prosseguir sem dados GSC, registrar no resumo final
- **Se dados não disponíveis:** basear as pautas em critério editorial + dados do GA4

---

### Passo 2 — Coletar dados do GA4 (opcional)

```bash
python execution/ga_report.py --days 30 --max 10
```

- Retorna os posts mais visitados dos últimos 30 dias
- **Se falhar por qualquer motivo:** prosseguir sem dados GA4, registrar no resumo final
- **Se dados não disponíveis:** basear as pautas em contexto sazonal + Tavily

---

### Passo 3 — Gerar 10 sugestões (Claude, inline)

Leia `directives/pauta-semanal.md` e aplique integralmente.

**Entradas:**
- Dados GSC do Passo 1
- Dados GA4 do Passo 2
- Data atual (para contexto sazonal)

**Saída esperada:** array JSON com 10 objetos de pauta.

---

### Passo 4 — Registrar pautas no Sheets

Para cada pauta gerada, execute:

```bash
python execution/sheets_write.py pauta --data '{
  "titulo": "...",
  "keyword": "...",
  "categoria": "...",
  "justificativa": "...",
  "status": "Pendente",
  "slug_sugerido": "..."
}'
```

Guardar os IDs retornados para referência.

---

### Passo 5 — Notificar via Telegram

Envie a lista de pautas como mensagem de texto formatada:

```bash
python execution/telegram_notify.py send-text --message "<lista formatada>"
```

**Formato da mensagem:**

```
📋 Pauta Semanal — [data]

1. [Título da pauta 1]
   Keyword: [keyword] | Cat: [categoria]
   [Justificativa]

2. [Título da pauta 2]
   ...

Para produzir uma pauta: claude "produzir pauta #N"
```

---

### Resumo final (Etapa 2A)

Exibir ao final:
```
=== Pauta Semanal Gerada ===
Data: [data]
Pautas geradas: 10
Dados GSC: [disponível / indisponível]
Dados GA4: [disponível / indisponível]
Registradas no Sheets: [N]
```

---

## Etapa 2B — Produção da pauta escolhida

### Ativação
```bash
claude "produzir pauta #N"
# N é o número da pauta na lista (1–10) ou o ID do Sheets
```

---

### Passo 1 — Buscar pauta no Sheets

```bash
python execution/sheets_read.py pautas --status "Pendente"
```

Identificar a pauta pelo número ou ID. Guardar: `titulo`, `keyword`, `categoria`, `wp_category_id`.

---

### Passo 2 — Atualizar status para "Produzindo"

```bash
python execution/sheets_write.py update-status \
  --tab "Pautas" \
  --row-id <id_da_pauta> \
  --status "Produzindo"
```

---

### Passo 3 — Buscar fontes (obrigatório)

Monte a query: `"<keyword> <cidade_principal> site:gov.br OR site:sp.gov.br OR site:prefeitura"`

```bash
python execution/search_sources.py \
  --query "<keyword> <cidade>" \
  --max 5
```

**Se `sufficient: false`:**
- Tentar query mais ampla sem restrição de site
- Se ainda `sufficient: false`:
  - Atualizar status: `sheets_write.py update-status --status "Sem fontes"`
  - Enviar mensagem no Telegram: `telegram_notify.py send-text`
  - Encerrar este fluxo

---

### Passo 4 — Escrever o post (Claude, inline)

Leia `directives/release-to-post.md` para guia de tom e estrutura.

**Entradas:**
- `titulo` e `keyword` da pauta
- Snippets das fontes retornadas pelo Tavily
- Categoria já definida

**Saída esperada (JSON interno):**
```json
{
  "titulo": "...",
  "slug": "...",
  "html": "...<p><em>Fontes: <a href='URL'>Título</a></em></p>",
  "wp_category_id": 19,
  "dados_ausentes": []
}
```

---

### Passo 5 — Pipeline de imagem

Não há anexos de email — ir direto para geração:

Monte a query: `"<tema principal> <cidade> <contexto visual>"`

```bash
python execution/image_generate.py --query "<query>" --slug <slug>
```

- Se retornar `source: unsplash`: salvar `credito_imagem` do resultado
- Se falhar: criar rascunho WP sem imagem, registrar no log

---

### Passo 6 — Arte para Instagram

```bash
python execution/instagram_image.py \
  --cover ".tmp/<slug>_cover.webp" \
  --slug "<slug>" \
  --title "<titulo>"
```

Gerar legenda usando `directives/social-instagram.md`.

---

### Passo 7 — Criar rascunho no WordPress

```bash
python execution/wp_publish.py create \
  --title "<titulo>" \
  --html "<html completo>" \
  --image-path ".tmp/<slug>_cover.webp" \
  --category-id <wp_category_id>
```

Guardar `post_id` e `edit_url`.

---

### Passo 8 — Registrar no Sheets

```bash
# Legenda IG
python execution/sheets_write.py legenda-ig --data '{
  "id_post": <post_id>,
  "titulo": "<titulo>",
  "legenda": "<legenda_gerada>",
  "hashtags": "<hashtags>",
  "status": "Pronta",
  "path_imagem": ".tmp/<slug>_ig.webp"
}'

# Atualiza status da pauta
python execution/sheets_write.py update-status \
  --tab "Pautas" \
  --row-id <id_pauta> \
  --status "Produzido"
```

---

### Passo 9 — Notificar via Telegram (aprovação)

```bash
python execution/telegram_notify.py send-release \
  --post-id <post_id> \
  --title "<titulo>" \
  --summary "<resumo 2-3 linhas>" \
  --edit-url "<edit_url>" \
  --cover ".tmp/<slug>_cover.webp" \
  --sheets-row-id <id_pauta> \
  --listen \
  --listen-timeout 1800
```

- [Publicar] → `wp_publish.py publish` → `sheets_write.py update-status "Publicado"`
- [Descartar] → `wp_publish.py trash` → `sheets_write.py update-status "Descartado"`

---

## Tratamento de erros

| Erro | Ação |
|------|------|
| `gsc_report.py` falha de auth | Continuar sem dados GSC, avisar no resumo |
| `ga_report.py` falha de auth | Continuar sem dados GA4, avisar no resumo |
| `search_sources.py` sem fontes | Marcar como "Sem fontes", notificar Telegram, parar |
| `wp_publish.py` erro 401 | Encerrar: "Falha auth WordPress" |
| `instagram_image.py` falha | Continuar sem arte IG, registrar no log |
