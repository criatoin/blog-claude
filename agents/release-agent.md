# Agente — Release → Post Aprovado

## Ativação
```bash
claude "processe releases"
# ou automaticamente via cron a cada hora
```

## Pré-requisitos
- `.env` configurado com GMAIL_*, WP_URL, WP_USER, WP_APP_PASSWORD
- Scripts em `execution/` funcionando (Etapa 1 + Etapa 2 validados)

---

## Passo 1 — Buscar emails não lidos

```bash
python execution/gmail_fetch.py --max 10 --output-dir .tmp
```

- Saída: JSON com lista de emails
- Se a lista estiver vazia: encerrar com mensagem "Nenhum email não lido na caixa."
- Processar cada email individualmente nos passos seguintes

---

## Passo 2 — Avaliar relevância (Claude, inline)

Para cada email, leia `subject`, `body_text` e `sender` e decida:

**Publicar se — AMBOS os critérios devem ser atendidos:**
1. Cidade: Americana, Santa Bárbara d'Oeste (SBO), Nova Odessa ou Sumaré
2. Tema: cultura, arte, música, teatro, cinema, dança, cursos/aulas gratuitas, ou diversão

**Não publicar se (qualquer um destes):**
- Tema é obra pública, saúde, saneamento, meio ambiente, política, administração
  municipal — mesmo que seja da cidade correta
- Cidade errada (outras regiões sem relação com o 019)
- Produto comercial, propaganda, newsletter, código de verificação, spam
- Release duplicado de evento já registrado no Log Releases

**Exemplos:**
- ✅ Curso gratuito de teatro em Americana
- ✅ Festival de música em Nova Odessa
- ❌ Construção de hospital em SBO (obra pública ≠ cultura/diversão)
- ❌ Grupo de trabalho de exportação (administrativo)
- ❌ Show em Campinas (cidade errada)

**Se não relevante:**
- Registrar: `{ "email_id": "...", "assunto": "...", "relevante": false, "motivo": "..." }`
- Pular para o próximo email

---

## Passo 3 — Reescrever o post (Claude, usando directives/release-to-post.md)

Leia `directives/release-to-post.md` e aplique integralmente.

Entrada: `subject` + `body_text` + `body_html` do email
Saída esperada (JSON interno):

```json
{
  "relevante": true,
  "categoria": "EVENTO FUTURO",
  "titulo": "...",
  "slug": "...",
  "html": "...",
  "dados_ausentes": [],
  "credito_imagem": ""
}
```

Se `dados_ausentes` não estiver vazio, incluir os marcadores `[DADO AUSENTE: ...]`
no HTML e registrar no log.

---

## Passo 4 — Pipeline de imagem (usando directives/image-select-resize.md)

Leia `directives/image-select-resize.md` para a lógica de decisão.

### 4a. Se o email tem anexos de imagem:

```bash
python execution/image_select.py --images <paths dos anexos>
```

- `score >= 4` → continuar com o path retornado
- `score < 4` → descartar, ir para 4b

### 4b. Processar a imagem selecionada ou gerar nova:

**Se tem imagem com score >= 4:**
```bash
python execution/image_process.py --input <path> --slug <slug>
```

**Se não tem imagem adequada:**

Monte a query: `"<tema principal> <cidade> <contexto visual>"`

```bash
python execution/image_generate.py --query "<query>" --slug <slug>
```

- Se retornar `source: unsplash`: salvar `credito_imagem` do resultado
- Se `image_generate.py` falhar: criar rascunho WP sem imagem, registrar no log

### Resultado final:
`cover_path = .tmp/{slug}_cover.webp`

---

## Passo 5 — Criar rascunho no WordPress

```bash
python execution/wp_publish.py create \
  --title "<titulo>" \
  --html "<html completo>" \
  --image-path ".tmp/<slug>_cover.webp" \
  --category-id <wp_category_id>
```

- Usar o `wp_category_id` retornado pelo Claude no Passo 3 (veja tabela em `directives/release-to-post.md`)
- Guardar `post_id` e `edit_url` do retorno
- Se `credito_imagem` não estiver vazio: o HTML já deve conter o crédito
  (inserido no Passo 3 pelo Claude)

---

## Passo 6 — Registrar no log (provisório — até Etapa 4)

Enquanto `sheets_write.py` não estiver disponível, imprimir o log em stdout:

```json
{
  "email_id": "...",
  "sender": "...",
  "subject": "...",
  "data_recebimento": "...",
  "relevante": true,
  "categoria": "EVENTO FUTURO",
  "titulo": "...",
  "slug": "...",
  "post_id": 123,
  "edit_url": "https://maisblog.com.br/wp-admin/...",
  "cover_path": ".tmp/..._cover.webp",
  "credito_imagem": "",
  "dados_ausentes": [],
  "status": "Aguardando aprovação"
}
```

---

## Passo 7 — Notificar via Telegram

Use `--listen` para que o listener suba imediatamente após o envio do card,
garantindo que o clique seja capturado dentro dos 60s do Telegram:

```bash
python execution/telegram_notify.py send-release \
  --post-id <post_id> \
  --title "<titulo>" \
  --summary "<resumo 2-3 linhas>" \
  --edit-url "<edit_url>" \
  --cover ".tmp/<slug>_cover.webp" \
  --sheets-row-id <id_log> \
  --listen \
  --listen-timeout 1800
```

- [Publicar] → `wp_publish.py publish` → `sheets_write.py update-status Publicado`
- [Descartar] → `wp_publish.py trash` → `sheets_write.py update-status Descartado`
- Confirmação de ação enviada automaticamente como mensagem no Telegram

---

## Tratamento de erros

| Erro | Ação |
|------|------|
| `gmail_fetch.py` falha de autenticação | Encerrar com erro claro: "Falha OAuth Gmail — verifique GMAIL_REFRESH_TOKEN" |
| `image_process.py` falha | Tentar `image_generate.py`; se também falhar, criar rascunho sem imagem |
| `wp_publish.py` retorna erro 401 | Encerrar: "Falha autenticação WordPress — verifique WP_APP_PASSWORD" |
| `wp_publish.py` retorna erro 500 | Registrar no log como erro, continuar com próximo email |
| Email com apenas imagem e sem texto | Tentar extrair do HTML; se vazio, marcar como "Não processável" no log |

---

## Resumo final

Após processar todos os emails, exibir:

```
=== Resumo do processamento ===
Total de emails: X
  Relevantes processados: X
  Não relevantes (descartados): X
  Erros: X
Rascunhos criados no WordPress: X
```
