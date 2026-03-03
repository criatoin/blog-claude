# Diretiva — Seleção e Processamento de Imagem

## Objetivo
Garantir que todo post publicado tenha uma imagem de capa 1920x1080px, WebP, <1MB,
com qualidade editorial adequada.

---

## Fluxo de decisão

```
Email tem anexos de imagem?
  SIM → Rodar image_select.py
          score >= 4 → Rodar image_process.py → .tmp/{slug}_cover.webp  ✓
          score < 4  → Descartar anexos → ir para "Sem imagem adequada"
  NÃO → ir para "Sem imagem adequada"

Sem imagem adequada → Rodar image_generate.py
  Tentativa 1: Unsplash (grátis)
  Tentativa 2: Gemini image generation (~$0.039)
  Tentativa 3: GPT Image 1 medium (~$0.04)
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

Monte a query com: **tema principal + cidade + contexto visual**.

Exemplos:
- `"festival de jazz americana sao paulo noite palco"`
- `"obras construcao hospital americana interior paulista"`
- `"curso gratuito culinaria aula cozinha"`

Evite queries muito genéricas ("evento", "notícia") — quanto mais específico, melhor o resultado do Unsplash.

---

## Crédito de imagem

- **Unsplash:** adicionar ao final do HTML do post: `<p><em>Foto: [Nome do fotógrafo] via Unsplash.</em></p>`
- **Gemini / GPT Image 1:** sem crédito necessário
- **Anexo do release:** sem crédito necessário (já é material de divulgação)

O campo `credito_imagem` no JSON de saída do Claude deve ser preenchido somente para Unsplash.

---

## Edge cases

| Situação | Ação |
|----------|------|
| Anexo é logo ou artefato gráfico (< 100KB) | Score automático 0 — descartar |
| Imagem tem marca d'água visível | Score automático 0 — descartar |
| Unsplash retorna 0 resultados para a query | Tentar query mais genérica (só cidade + tema) antes de ir para Gemini |
| Todas as tentativas de geração falham | Registrar erro no log, criar rascunho WP sem imagem destacada |
