# Diretiva — Seleção e Processamento de Imagem

## Objetivo
Garantir que todo post publicado tenha uma imagem de capa 1920x1080px, WebP, <1MB,
com qualidade editorial adequada.

---

## Fluxo de decisão

```
Email tem anexos de imagem?
  SIM → Rodar image_select.py
          score >= 4 + vision OK → Rodar image_process.py → .tmp/{slug}_cover.webp  ✓
          score < 4 ou vision rejeita → Descartar anexos → ir para "Sem imagem adequada"
  NÃO → ir para "Sem imagem adequada"

Sem imagem adequada → LLM gera query focada na atividade/pessoas → Rodar image_generate.py
  Tentativa 1: Unsplash (grátis)
  Tentativa 2: Pexels (grátis)
  Tentativa 3: Gemini image generation (~$0.039)
  Tentativa 4: GPT Image 1 medium (~$0.04)
  → Resultado sempre passa por image_process.py → .tmp/{slug}_cover.webp  ✓
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

## Verificação de relevância via Gemini Vision

Aplicada em **duas etapas**:

### 1. Anexos de email (`run_releases.py` → `_imagem_relevante`)
Após `image_select.py` aprovar o score técnico, antes de `image_process.py`.
Verifica: foto real + relevante ao título.
Em caso de falha da vision API, a imagem é **rejeitada** (vai para Unsplash/Gemini) — mais seguro que aceitar.

### 2. Imagens de stock (`image_generate.py` → `_validate_image`)
Aplicada a **cada candidato** do Unsplash/Pexels antes de aceitar.
Verifica **três condições obrigatórias**:
1. A imagem é uma **fotografia real** (não logo, não gráfico, não banner, não flyer)
2. A fotografia é **visualmente relacionada** ao título do post
3. A imagem **não tem texto proeminente** (cartazes, banners, legendas sobrepostas)

O Unsplash/Pexels tentam até 5 candidatos em ordem. O primeiro que passar nas 3 condições é usado.
Se todos falharem, o pipeline avança para Gemini/OpenAI.
Em caso de falha da vision API durante validação de stock, a imagem é **aceita** (já é fallback — mais tolerante).

---

## Edge cases

| Situação | Ação |
|----------|------|
| Anexo é logo ou artefato gráfico (< 100KB) | Score automático 0 — implementado em `image_select.py` |
| Imagem tem marca d'água visível | Score automático 0 — descartar |
| Unsplash retorna 0 resultados para a query | Tentar query mais genérica (só cidade + tema) antes de ir para Gemini |
| Todas as tentativas de geração falham | Registrar erro no log, criar rascunho WP sem imagem destacada |
