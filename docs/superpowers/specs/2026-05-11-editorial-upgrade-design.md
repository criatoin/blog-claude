# Design Spec — Upgrade Editorial do Pipeline de Releases
**Data:** 2026-05-11  
**Escopo:** `execution/editorial.py` (novo) + `execution/run_releases.py` + `execution/telegram_notify.py` + `execution/instagram_image.py`  
**Fase:** 1 — somente pipeline de releases. Pautas ficam para fase 2.  
**Status:** Aprovado para implementação

---

## Contexto e Problema

O pipeline atual converte releases em posts funcionais, mas o conteúdo soa como "release reescrito" — linguagem institucional, títulos fracos, legendas genéricas. O objetivo desta fase é melhorar a camada editorial sem alterar a arquitetura de infraestrutura (imagens, WP, Sheets, Telegram bot continuam iguais).

**Princípio central:** a IA atua como editora assistente, não criadora livre. Ela melhora a forma de contar, nunca inventa o que aconteceu.

---

## O que muda e o que não muda

### Não muda (intocável nesta fase)
- `gmail_fetch.py` — fetch de emails
- `image_generate.py`, `image_process.py`, `image_select.py` — pipeline de imagens
- `instagram_image.py` — template visual determinístico (só aceita 2 novos args opcionais)
- `wp_publish.py` — publicação WordPress
- `sheets_write.py`, `sheets_read.py` — Sheets
- `telegram_bot.py` — daemon de callbacks
- `llm_call.py` — wrapper LLM
- Arquitetura visual das artes (Pillow, gradiente, badge, logo)

### Muda
- `execution/editorial.py` — **criado** com 6 funções
- `execution/run_releases.py` — funções LLM internas substituídas pelas do módulo editorial
- `execution/telegram_notify.py` — card enriquecido com scores e alertas
- `execution/instagram_image.py` — aceita `--art-title` e `--art-subtitle` opcionais

---

## Arquitetura: módulo `editorial.py`

### Constante de modelo

```python
EDITORIAL_MODEL = os.getenv("EDITORIAL_MODEL", "deepseek/deepseek-chat")
```

Permite trocar o modelo por variável de ambiente sem alterar código. Durante testes, setar `EDITORIAL_MODEL=google/gemini-flash-1.5` ou `anthropic/claude-haiku-4-5` no `.env` local para comparar qualidade.

### Voz editorial (bloco fixo injetado em todos os prompts de redação)

```
Você é o editor assistente do +blog, portal regional de cultura, diversão e vida nas cidades
de Americana, Santa Bárbara d'Oeste, Nova Odessa e Sumaré.

Sua função é transformar informações confirmadas em conteúdo com linguagem leve, local, útil
e compartilhável. O +blog não escreve como assessoria de imprensa.

Tom: leve, claro, regional, informativo sem ser duro, próximo sem exagerar na informalidade,
positivo e comunitário, frases curtas, sem sensacionalismo, sem parecer propaganda.

Evite: "o evento promete", "imperdível" em excesso, "confira" repetidamente, linguagem
institucional, copiar a ordem do release, títulos longos, hashtags genéricas, "evento acontece em...".

Priorize: benefício para o público, cidade logo no início quando relevante, se é gratuito /
quando / onde / para quem, gancho humano ou cultural, título com curiosidade ou pertencimento.

REGRA FACTUAL OBRIGATÓRIA: afirme apenas informações presentes no release original ou no
JSON de fatos. Nunca invente datas, horários, locais, atrações, preços, cidades, links ou
formas de inscrição.
```

---

## As 6 funções do `editorial.py`

### Função 1 — `extrair_fatos(release_text: str) -> dict`

**LLM call:** sim (1 call, prompt curto)  
**Entrada:** texto bruto do release  
**Saída:** dict com os campos abaixo  
**Fallback:** dict com todos os campos vazios/null se LLM falhar ou JSON inválido

```json
{
  "cidade": "",
  "local": "",
  "endereco": "",
  "data": "",
  "horario": "",
  "periodo": "",
  "valor": "",
  "gratuito": null,
  "inscricao_necessaria": null,
  "link_inscricao": "",
  "atracoes": [],
  "artistas": [],
  "projeto": "",
  "instituicao_realizadora": "",
  "publico_alvo": "",
  "categoria_editorial": "",
  "resumo_factual": "",
  "informacoes_ausentes": [],
  "observacoes": [],
  "creditos_texto": "",
  "creditos_fotos": ""
}
```

`creditos_texto` e `creditos_fotos` extraídos do release quando presentes (assessoria, fotógrafo, MTb, etc.).

---

### Função 2 — `avaliar_relevancia(release_text: str, fatos: dict) -> dict`

**LLM call:** sim (1 call)  
**Substitui:** `_llm_relevancia()` em `run_releases.py`  
**Entrada:** release + fatos extraídos  
**Saída:**

```json
{
  "relevante": true,
  "cidade": "",
  "categoria_editorial": "",
  "relevancia_editorial": 0,
  "potencial_google": 0,
  "potencial_instagram": 0,
  "potencial_compartilhamento": 0,
  "urgencia": 0,
  "formato_ideal": "",
  "angulo_recomendado": "",
  "motivo_aprovacao_ou_descarte": "",
  "observacao_para_editor": ""
}
```

**Critérios de relevância (no prompt):**
1. Relação com Americana, SBO, Nova Odessa ou Sumaré?
2. Valor para moradores da região?
3. Apelo cultural, social, educativo, turístico, gastronômico, comunitário ou de lazer?
4. Pode gerar clique no site?
5. Pode gerar compartilhamento no Instagram?
6. Conteúdo útil, interessante ou relevante para a comunidade?

**Fallback:** `{"relevante": false, "motivo_aprovacao_ou_descarte": "Erro na avaliação"}` — pipeline descarta com segurança.

---

### Função 3 — `gerar_conteudo(release_text: str, fatos: dict, avaliacao: dict) -> dict`

**LLM call:** sim (1 call — o mais pesado, ~2000 tokens de saída)  
**Substitui:** `_llm_reescrever()` em `run_releases.py`  
**Entrada:** release + fatos + `angulo_recomendado` da avaliação  
**O `angulo_recomendado` é injetado no prompt como instrução editorial antes da voz editorial**

**Saída:**

```json
{
  "titulo_site": "",
  "titulo_social": "",
  "titulo_arte": "",
  "subtitulo": "",
  "slug": "",
  "categoria": "",
  "wp_category_id": 12,
  "tags": [],
  "resumo_telegram": "",
  "html": "",
  "texto_arte": {
    "titulo_principal": "",
    "linha_apoio": "",
    "badge": "",
    "alerta": ""
  },
  "creditos": {
    "texto": "",
    "fotos": ""
  }
}
```

**Regras dos títulos (no prompt):**
- `titulo_site`: claro, buscável, SEO (máx 65 chars)
- `titulo_social`: mais leve e chamativo, sem distorcer fato
- `titulo_arte`: máx 6 palavras, sem ponto final
- `slug`: simples, otimizado, sem acentos
- `titulo_principal` (arte): máx 6 palavras
- `linha_apoio` (arte): máx 12 palavras

**Créditos no HTML:** o bloco de créditos é inserido automaticamente ao final do `html` no formato:
```html
<p><em>Texto: [creditos.texto], reescrito pela equipe do +blog. Fotos: [creditos.fotos]</em></p>
```
Se `creditos.texto` vier vazio dos fatos, usa o sender do email como fallback. Se `creditos.fotos` vier vazio, usa "Divulgação".

**Fallback:** retorna dict com campos vazios + `titulo_site` derivado do assunto do email.

---

### Função 4 — `gerar_legenda(fatos: dict, resumo: str) -> dict`

**LLM call:** sim (1 call)  
**Substitui:** `_llm_legenda_ig()` em `run_releases.py`  
**Entrada:** fatos extraídos + resumo da matéria  

**Saída:**

```json
{
  "legenda_curta": "",
  "legenda_contexto": "",
  "cta_sugerido": "",
  "hashtags": []
}
```

**CTAs rotativos (no prompt, IA escolhe o mais adequado ao conteúdo):**
- "Salva pra lembrar desse rolê." — apenas se houver data/agenda
- "Marca quem iria com você."
- "A programação completa está no +blog." — apenas se existir programação completa
- "Mais detalhes estão no nosso portal."
- "Quer ver mais rolês assim por aqui? Comenta 'eu quero'."
- "A gente colocou tudo no +blog pra você se programar melhor."
- "Já manda pra quem vive procurando o que fazer na região."

**Regra:** máx 5 hashtags, regionais e específicas. `legenda_curta` vai para o card do Telegram e para uso padrão. `legenda_contexto` salva no Sheets para o editor escolher.

---

### Função 5 — `validar_fatos(release_text: str, fatos: dict, post: dict) -> dict`

**LLM call:** sim (1 call)  
**Entrada:** release original + fatos extraídos + post gerado (matéria + títulos + legenda)  

**Saída:**

```json
{
  "aprovado": true,
  "risco_alucinacao": "baixo",
  "problemas": [
    {
      "trecho": "",
      "problema": "",
      "correcao_sugerida": ""
    }
  ],
  "observacao_editorial": ""
}
```

**Verifica:** datas, horários, cidade, local, valor, gratuidade, atrações, nomes de pessoas/projetos/instituições, links, inscrição, público-alvo, chamadas exageradas.

**Fallback:** `{"aprovado": true, "risco_alucinacao": "baixo", "problemas": []}` — não bloqueia o pipeline se o validador falhar. Log de aviso no stderr.

---

### Função 6 — `resumo_telegram(post: dict, validacao: dict, avaliacao: dict) -> dict`

**LLM call:** não — monta o dict a partir dos dados já gerados. Zero custo adicional.

**Saída:**

```json
{
  "titulo_card": "",
  "cidade": "",
  "categoria": "",
  "por_que_importa": "",
  "potencial_site": "",
  "potencial_instagram": "",
  "urgencia": "",
  "acao_recomendada": "",
  "alertas": []
}
```

`alertas` recebe os problemas do validador quando `risco_alucinacao` for `medio` ou `alto`.

---

## Novo fluxo em `processar_email()` — `run_releases.py`

```
1.  extrair_fatos(body_text)
2.  avaliar_relevancia(body_text, fatos)
    └─ relevante=false → sheets_write log-release (descartado) + return
3.  gerar_conteudo(body_text, fatos, avaliacao)
4.  _pipeline_imagem(email, post["slug"], post["titulo_site"])
    └─ query gerada a partir de fatos["categoria_editorial"] + fatos["atracoes"]
       sem chamada LLM adicional
5.  gerar_legenda(fatos, post["resumo_telegram"])
6.  validar_fatos(body_text, fatos, post)
7.  resumo_telegram(post, validacao, avaliacao)
8.  instagram_image.py
    └─ --art-title  = post["texto_arte"]["titulo_principal"]
    └─ --art-subtitle = post["texto_arte"]["linha_apoio"]
9.  wp_publish.py create
    └─ título = post["titulo_site"]
    └─ html = post["html"] (já com bloco de créditos ao final)
10. sheets_write.py log-release
11. sheets_write.py legenda-ig
    └─ legenda = legendas["legenda_curta"]
    └─ hashtags = legendas["hashtags"] (lista)
    └─ campo "legenda_contexto" = legendas["legenda_contexto"] — VER NOTA ABAIXO
12. telegram_notify.py send-release
    └─ recebe --card-meta (JSON) com resumo_telegram
```

> **NOTA — legenda_contexto no Sheets:** a spec não adiciona coluna nova automaticamente. A decisão de criar uma coluna `legenda_longa` na aba Legendas IG fica para o editor decidir antes da implementação. Por ora, `legenda_contexto` é descartada (não salva). Se o usuário quiser preservá-la, criar a coluna `legenda_longa` na aba Legendas IG e ajustar `sheets_write.py` para incluí-la. **Decisão pendente do usuário.**

---

## Mudanças em `telegram_notify.py`

### Argumento novo em `send-release`
```
--card-meta  JSON string com campos de resumo_telegram
```

### Formato do card (texto montado localmente, sem LLM)
```
{titulo_card}
📍 {cidade} · {categoria}

{por_que_importa}

📊 Site {potencial_site}/10 · Instagram {potencial_instagram}/10
⏰ Urgência: {urgencia}
💡 {acao_recomendada}

[⚠️ Revisar antes de aprovar: {alertas}]  ← só se risco médio/alto
```

Botões inalterados: ✅ Site · 📸 Instagram · 🗑 Descartar

---

## Mudanças em `instagram_image.py`

Dois argumentos novos, **opcionais**:
```
--art-title     título principal da arte (máx 6 palavras)
--art-subtitle  linha de apoio da arte (máx 12 palavras)
```

Se passados, substituem a derivação atual do título do post. Se não passados, comportamento atual mantido (compatibilidade total com fase 2 de pautas).

---

## Query de imagem sem LLM extra

A função `_gerar_query_imagem()` atual faz uma chamada LLM. Com os fatos extraídos disponíveis, essa chamada é eliminada:

```python
def _query_from_fatos(fatos: dict, titulo: str) -> str:
    partes = []
    if fatos.get("atracoes"):
        partes.append(fatos["atracoes"][0])
    if fatos.get("categoria_editorial"):
        partes.append(fatos["categoria_editorial"])
    return " ".join(partes) or titulo[:60]
```

Economia de 1 call LLM por email que vai para busca de imagem.

---

## Resumo de calls LLM por email

| Situação | Calls atuais | Calls novos |
|----------|-------------|------------|
| Email descartado | 1 | 2 (extração + avaliação) |
| Email relevante | 3 | 5 (extração + avaliação + conteúdo + legenda + validação) |

O custo por email relevante sobe de 3 para 5 calls, mas elimina a call de query de imagem. A qualidade editorial melhora em todas as dimensões. Com DeepSeek (muito barato), o custo total ainda é baixo — e o modelo pode ser trocado por variável de ambiente a qualquer momento.

---

## Teste de modelo

Para comparar modelos antes de escolher o padrão definitivo:

1. Setar `EDITORIAL_MODEL=google/gemini-flash-1.5` no `.env` local
2. Rodar `python execution/run_releases.py --dry-run` com um email de teste
3. Comparar saída JSON de `gerar_conteudo()` entre modelos
4. Escolher o modelo que der melhor resultado em português regional
5. Atualizar `EDITORIAL_MODEL` padrão no código

---

## Segurança editorial — regras codificadas nos prompts

Sempre que faltar dado, a IA é conservadora:

| Dado ausente | O que fazer |
|-------------|------------|
| Gratuidade não confirmada | não escrever "gratuito" |
| Horário não confirmado | não mencionar horário |
| Cidade não clara | campo `cidade` = "" + `observacoes` com alerta |
| Data não confirmada | não usar CTA "salva pra não esquecer" |
| Inscrição não confirmada | não mencionar inscrição |

---

## Decisão pendente

**Legenda longa no Sheets:** criar coluna `legenda_longa` na aba Legendas IG para armazenar `legenda_contexto` separadamente? Impacta `sheets_write.py` e o setup da planilha. Recomendo criar — é um campo valioso. Decisão do usuário antes de iniciar a implementação.

---

## Fora do escopo desta fase

- Stories Instagram
- Pipeline de pautas (`run_pauta_produce.py`, `run_pauta_generate.py`)
- Alterações visuais nas artes determinísticas
- Posting automático no Instagram
- Novos campos no Sheets além de `legenda_longa` (se aprovado)
