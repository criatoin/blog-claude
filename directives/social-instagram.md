# Diretiva — Legenda e Arte para Instagram +blog

## Objetivo
Produzir legenda e arte para o Instagram do +blog a partir de um post já escrito,
mantendo o tom do portal e maximizando o engajamento local.

---

## Identidade Instagram do +blog

**Canal:** portal de cultura e diversão de Americana, SBO, Nova Odessa e Sumaré.
**Público:** morador da região, 20–45 anos, curioso sobre a agenda local.
**Tom:** direto, convidativo, levemente informal. Sem juridiquês, sem corporativês, sem emoji excessivo.

---

## Estrutura da Legenda

### Bloco 1 — Gancho (obrigatório)
1–2 linhas que param o scroll. Deve gerar curiosidade ou urgência.

**Exemplos bons:**
- `Festival de Jazz grátis em Americana neste fim de semana.`
- `Inscrições abertas: curso de teatro gratuito em SBO.`
- `Marco Haurélio no Círculo do Livro — uma noite de cordel em Santa Bárbara.`

**Errado:** começar com "Ei!", "Oi!", "Olá!" ou emoji.

---

### Bloco 2 — Serviço (obrigatório para EVENTO FUTURO)
Data, local, entrada. Uma informação por linha, sem bullet points.

```
Quando: [data completa e horário]
Onde: [nome do local e cidade]
Entrada: [gratuita / valor / como obter ingresso]
```

---

### Bloco 3 — CTA (obrigatório)
Uma linha. Escolha um dos modelos:
- `Confira todos os detalhes no site — link na bio.`
- `Mais informações no link da bio.`
- `Marca quem vem!`
- `Salva esse post para não esquecer.`

---

### Bloco 4 — Hashtags (8–12 tags)
Misture: tema + cidade + região + portal.

**Tags fixas do portal:**
`#maisblog #agenda019 #019`

**Tags de cidade (use a(s) cidade(s) do evento):**
`#americana #americanasp #sbodoeste #santabarbara #novaodessa #sumare`

**Tags de tema (escolha as relevantes):**
`#agendacultural #culturarb #teatrob #musicasp #cursogratuito #festivaldejazz`
`#exposicao #cinema #danca #literatura #gastronomia #festejosjuninos`

**Formato final:**
```
[linha em branco antes das tags]
#maisblog #agenda019 #019 #americana #agendacultural #[tema] ...
```

---

## Arte para Instagram

### Formato
- **Resolução:** 1080 × 1350 px (4:5 — vertical, ocupa mais espaço no feed)
- **Formato de arquivo:** WebP, <1MB
- **Caminho de saída:** `.tmp/{slug}_ig.webp`

### Geração via instagram_image.py

```bash
python execution/instagram_image.py \
  --cover ".tmp/{slug}_cover.webp" \
  --slug "{slug}" \
  --title "{titulo}" \
  --category "{nome_da_categoria}"
```

O script usa composição local via Pillow (sem API externa):
1. Imagem de referência dos modelos em `assets/instagram/` (8.jpg ou 6.jpg)
2. A capa do post como base visual
3. Sobreposição de título e elementos gráficos gerada diretamente pelo script

Após gerar a arte, fazer upload para WP Media Library para obter URL pública:
```bash
python execution/wp_publish.py upload-image \
  --image-path ".tmp/{slug}_ig.webp" \
  --title "{titulo} — Instagram"
```
A URL retornada (`url`) é salva na coluna path_imagem da aba Legendas IG.

Se o script falhar, use a imagem da capa como arte de Instagram mesmo.

---

## Saída esperada do Claude

Retorne um objeto JSON com:

```json
{
  "legenda": "Festival de Jazz grátis em Americana neste fim de semana.\n\nQuando: sábado, 15 de março, a partir das 19h\nOnde: Parque Urbano, Americana\nEntrada: gratuita\n\nMais informações no link da bio.\n\n#maisblog #agenda019 #019 #americana #agendacultural #festivaldejazz #musicasp",
  "hashtags": ["#maisblog", "#agenda019", "#019", "#americana", "#agendacultural", "#festivaldejazz", "#musicasp"]
}
```

---

## Regras gerais

- Nunca inventar data, local ou valor que não esteja no release/post
- Se faltar informação de serviço, omitir o bloco Serviço e compensar com contexto no gancho
- A legenda deve ser autossuficiente — o leitor não precisa clicar para entender o evento
- Não repetir o título do post na legenda palavra por palavra — reformule o gancho
