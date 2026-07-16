# Diretiva — Seleção e Processamento de Imagem

## Objetivo
Garantir que todo post publicado tenha uma imagem de capa 1920x1080px, WebP, <1MB,
com qualidade editorial adequada — e que, quando isso não for possível
automaticamente, **nunca se publique com placeholder ou foto não verificada em
silêncio**: o operador humano decide via Telegram.

---

## Fluxo de decisão

```
Email tem anexos de imagem?
  SIM → Rodar image_select.py
          score >= 4 + vision = "yes"          → image_process.py → .tmp/{slug}_cover.webp  ✓ (capa automática)
          score >= 4 + vision = "unavailable"  → vira SUGESTÃO (não aprova sozinha), tenta próximo candidato
          score < 4 ou vision = "no"           → descarta este anexo, tenta próximo
  NÃO → segue para banco de imagens

Nenhum anexo aprovado automaticamente → LLM gera query focada na atividade/pessoas → image_generate.py
  Tentativa 1: Unsplash (grátis)
  Tentativa 2: Pexels (grátis)
  Tentativa 3: Gemini image generation (~$0.039)
  Tentativa 4: GPT Image 1 medium (~$0.04)
  → Candidato validado ("yes")   → image_process.py → .tmp/{slug}_cover.webp  ✓ (capa automática)
  → Candidato "unavailable"      → vira SUGESTÃO (se ainda não há uma melhor)

Se, ao final de tudo, não há capa automática (só sugestão ou nada):
  → run_releases.py NÃO publica sem imagem nem usa a sugestão sozinho
  → Telegram recebe card `⚠️ Sem imagem adequada` (send-image-pending) com:
      [✔️ Usar sugestão]  (só aparece se houver suggestion_path)
      [📷 Vou enviar foto]
  → "Usar sugestão": completa o rascunho com a imagem não validada, sob decisão humana
  → "Vou enviar foto": bot aguarda a próxima foto enviada no chat e a usa como capa
```

---

## Sistema de score (image_select.py)

| Critério | Pontos |
|----------|--------|
| Resolução ≥ 1920×1080 | +2 |
| Resolução ≥ 1280×720 | +1 |
| Aspect ratio 16:9 (ratio entre 1.6 e 2.0) | +2 |
| Aspect ratio alargado (ratio entre 1.4 e 2.2) | +1 |
| Dimensões mínimas 800×450 | +1 |
| Tamanho do arquivo < 8MB | +1 |
| Orientação landscape | +1 |

**Score máximo:** 8 — **Threshold de aprovação:** 4

---

## Processamento (image_process.py)

1. Smart crop centralizado para exatamente 1920×1080px
2. Conversão para WebP com compressão progressiva:
   - quality=85 → se ainda >1MB
   - quality=75 → se ainda >1MB
   - quality=65 → se ainda >1MB
   - quality=55 (último recurso)
3. Destino: `.tmp/{slug}_cover.webp`

---

## Query para image_generate.py

A query é gerada automaticamente via LLM (`_gerar_query_imagem()`) a partir do título do post.

**Regras do LLM para gerar a query:**
1. Foco na **atividade/pessoas** — nunca no nome da cidade ou landmarks locais
2. Stock photos (Unsplash/Pexels) não têm fotos de cidades específicas do interior brasileiro
3. Prefira mostrar **pessoas reais fazendo a atividade**
4. Evento fitness → pessoas se exercitando
5. Evento cultural/arte → a forma de arte ou o público
6. Evento gastronômico → a comida ou pessoas comendo
7. Palestra/talk → plateia em auditório ou palestrante
8. Query em inglês (3-6 palavras) para Unsplash/Pexels

**Exemplos corretos:**
- "SBO Por Elas — palestra e aulão de condicionamento físico" → `"women group fitness class aerobics"`
- "Festival de Jazz em Americana" → `"jazz concert outdoor festival crowd"`
- "Curso de culinária gratuito" → `"cooking class students kitchen"`

**Exemplos errados (nunca fazer):**
- `"santa barbara doeste parque evento"` — cidade específica + landmark
- `"americana sp festival jazz palco"` — cidade no nome da query

---

## Crédito de imagem

- **Unsplash:** adicionar ao final do HTML do post: `<p><em>Foto: [Nome do fotógrafo] via Unsplash.</em></p>`
- **Gemini / GPT Image 1:** sem crédito necessário
- **Anexo do release:** sem crédito necessário (já é material de divulgação)

O campo `credito_imagem` no JSON de saída do Claude deve ser preenchido somente para Unsplash.

---

## Verificação de relevância via Gemini Vision — tri-state `yes`/`no`/`unavailable`

Tanto `_imagem_relevante` (`run_releases.py`, para anexos de email) quanto
`_validate_image` (`image_generate.py`, para stock/geração) retornam um de
três veredictos, nunca um booleano simples:

- **`"yes"`** — vision rodou e aprovou: imagem real, relevante ao título, sem
  texto proeminente. Vira capa automática.
- **`"no"`** — vision rodou e rejeitou (não é fotografia real, texto/marca
  d'água proeminente, ou tema incompatível). Candidato descartado, tenta o
  próximo.
- **`"unavailable"`** — a vision **não conseguiu rodar** (sem
  `GEMINI_API_KEY`, ou a API respondeu **503/UNAVAILABLE**, indicando
  sobrecarga temporária do Gemini). **`"unavailable"` nunca é tratado como
  aprovação automática** — em ambos os fluxos (anexo de email e stock), um
  candidato "unavailable" vira no máximo uma **sugestão não validada**
  (`suggestion_path`), nunca a capa final do post. Essa é a mudança central:
  antes um 503 podia acabar aprovando a imagem por omissão; hoje ele é tratado
  como "não sei", e a decisão final fica para o operador humano no card
  `⚠️ Sem imagem adequada`.

### 1. Anexos de email (`run_releases.py` → `_imagem_relevante`)
Após `image_select.py` aprovar o score técnico, antes de `image_process.py`.
Verifica: foto real + relevante ao título. `"yes"` vira capa; `"no"` descarta
o anexo; `"unavailable"` vira sugestão (primeira encontrada é mantida).

### 2. Imagens de stock (`image_generate.py` → `_validate_image`)
Aplicada a **cada candidato** do Unsplash/Pexels antes de aceitar.
Verifica **três condições obrigatórias**:
1. A imagem é uma **fotografia real** (não logo, não gráfico, não banner, não flyer)
2. A fotografia é **visualmente relacionada** ao título do post
3. A imagem **não tem texto proeminente** (cartazes, banners, legendas sobrepostas)

O Unsplash/Pexels tentam até 5 candidatos em ordem. O primeiro `"yes"` é usado
como capa automática. Se todos falharem (`"no"`) ou só renderem
`"unavailable"`, o pipeline avança para Gemini/OpenAI image generation; se
mesmo assim não houver `"yes"`, o melhor candidato `"unavailable"` (se houver)
vira sugestão para o card de pendência.

---

## Sem placeholder, sem fallback silencioso — card `send-image-pending`

Quando o pipeline termina sem uma capa aprovada automaticamente
(`cover_path` vazio), `run_releases.py` **não** cria o rascunho com imagem
genérica nem publica sem foto. Ele chama
`telegram_notify.py send-image-pending` com o `suggestion_path` (se houver) e
o Telegram mostra:

- `⚠️ Sem imagem adequada` — texto do card.
- Botão `[✔️ Usar sugestão]` — só aparece se existir uma sugestão não
  validada; aciona o callback `usethis:<post_id>`, que completa o rascunho
  com essa imagem sob decisão explícita do operador.
- Botão `[📷 Vou enviar foto]` — aciona `sendphoto:<post_id>`; o bot
  (`telegram_bot.py`) entra em modo de espera e a **próxima foto enviada no
  chat** é baixada e usada como capa, resolvendo a pendência.

Isso substitui qualquer comportamento anterior de fallback silencioso (ex.:
publicar sem imagem destacada) — a pendência fica visível e a decisão é
sempre humana.

---

## Edge cases

| Situação | Ação |
|----------|------|
| Anexo é logo ou artefato gráfico (< 100KB) | Score automático 0 — implementado em `image_select.py` |
| Imagem tem marca d'água visível | Score automático 0 — descartar |
| Unsplash retorna 0 resultados para a query | Tentar query mais genérica (só cidade + tema) antes de ir para Gemini |
| Vision retorna 503 (sobrecarga) | Veredito `"unavailable"` — candidato vira sugestão, nunca aprovação automática |
| Sem `GEMINI_API_KEY` configurada | Veredito `"unavailable"` em toda chamada de vision — mesmo tratamento acima |
| Todas as tentativas de geração falham | Card `⚠️ Sem imagem adequada` ao Telegram com `[Usar sugestão]`/`[Vou enviar foto]` — nunca publica sem decisão humana |
