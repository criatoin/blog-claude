# Diretiva — Release para Post +blog

## Objetivo
Transformar um release de assessoria de imprensa em post publicável no +blog,
mantendo 100% dos dados originais, no tom do portal e no formato HTML correto.

---

## Identidade editorial do +blog

**O +blog é o portal de cultura e diversão de Americana, Santa Bárbara d'Oeste,
Nova Odessa e Sumaré.** O leitor é morador da região, informal, curioso, ocupado.

**Tom:**
- Natural e direto. Escreva como quem conta uma novidade para um amigo da cidade.
- Frases curtas. Parágrafos de 2–3 linhas.
- Sem juridiquês: proibido "no que tange", "haja vista", "consoante", "outrossim".
- Sem corporativês: proibido "robusto", "sinergia", "ecossistema", "stakeholders".
- Sem emoji.
- Nunca inventar dados. Se faltar informação (horário, endereço, valor), sinalize
  com `[DADO AUSENTE: descrição]` no HTML e registre no log.

---

## Categorias e estrutura HTML

### [EVENTO FUTURO]
Evento com data definida no futuro (show, feira, festival, palestra, curso, exposição).

```html
<p><strong>LEAD:</strong> 1–2 frases respondendo: o quê, quando, onde, quem.</p>

<p>Parágrafo de contexto: por que este evento é relevante para o leitor? O que ele
vai encontrar lá? Citação do organizador se houver (com atribuição).</p>

<p>Mais detalhes: programação, atrações, destaques. Use os dados do release sem
sintetizar demais — cada atração merece ser mencionada.</p>

<h2>Serviço</h2>
<ul>
  <li><strong>O quê:</strong> [nome do evento]</li>
  <li><strong>Quando:</strong> [data e horário]</li>
  <li><strong>Onde:</strong> [endereço completo]</li>
  <li><strong>Entrada:</strong> [gratuita / valor / como obter ingresso]</li>
  <li><strong>Mais informações:</strong> [telefone / site / redes sociais]</li>
</ul>
```

---

### [NOTÍCIA/ANÚNCIO]
Novidade institucional, obra, serviço público, resultado, conquista.

```html
<p><strong>LEAD:</strong> O fato principal em 1–2 frases. Quem fez o quê.</p>

<p>Contexto: por que isso importa para o morador da cidade? Qual problema resolve
ou qual avanço representa?</p>

<p>Detalhes: números, prazos, etapas, declarações. Use os dados do release.</p>

<p>Se houver desdobramentos ou próximos passos, mencione no último parágrafo.</p>
```

---

### [RETROSPECTIVA]
Balanço, resultado, relatório de evento já realizado.

```html
<p><strong>LEAD:</strong> O resultado principal em 1–2 frases.</p>

<p>Como foi: dados, números, destaques, público presente.</p>

<p>Reações e declarações: citações de organizadores, participantes, autoridades.</p>

<p>Próxima edição ou desdobramentos, se houver.</p>
```

---

### [AGENDA MÚLTIPLA]
Várias atrações ou eventos num mesmo post (ex: programação semanal).

```html
<p>Introdução: o que está rolando na cidade neste período.</p>

<h2>[Nome do Evento 1]</h2>
<p>Descrição curta.</p>
<ul>
  <li><strong>Quando:</strong> ...</li>
  <li><strong>Onde:</strong> ...</li>
  <li><strong>Entrada:</strong> ...</li>
</ul>

<h2>[Nome do Evento 2]</h2>
<!-- repetir o bloco para cada evento -->
```

---

## Regras de SEO

- **Título:** máximo 65 caracteres. Deve conter o nome da cidade + tema principal.
  Exemplos: `"Festival de Jazz chega a Americana em abril"`,
  `"Prefeitura abre inscrições para curso gratuito de culinária em SBO"`
- **Slug:** gerado a partir do título em lowercase, hífens, sem acentos, sem stop words.
  Exemplo: `festival-jazz-americana-abril`
- **Primeira ocorrência do keyword:** deve estar no primeiro parágrafo.
- **Meta description:** primeira frase do lead (será extraída automaticamente pelo WP).

---

## Critérios de relevância

**Publicar se — TODOS os critérios devem ser atendidos:**
1. É das cidades: Americana, Santa Bárbara d'Oeste (SBO), Nova Odessa ou Sumaré
2. O tema é UM DESTES: cultura, arte, música, teatro, cinema, dança,
   cursos/aulas gratuitas, ou diversão

**Não publicar (registrar como "Não relevante" no log):**
- Obras, saúde pública, saneamento, meio ambiente, política, administração
  municipal — mesmo que sejam de Americana ou SBO
- Esporte profissional ou competitivo (exceto se for evento aberto ao público como diversão)
- Apenas outras cidades sem relação com a região do 019
- Produto comercial, propaganda ou press release sem conteúdo editorial
- Release duplicado (mesmo evento já registrado no Log Releases)

**Exemplos práticos:**
- ✅ Curso gratuito de teatro em Americana → cultura + gratuito + cidade correta
- ✅ Festival de música em Nova Odessa → arte + cidade correta
- ✅ Aula gratuita de culinária em SBO → curso gratuito + cidade correta
- ❌ Construção de hospital em SBO → obra pública, não é cultura/diversão
- ❌ Grupo de trabalho de exportação em Americana → administrativo
- ❌ Show pago em Campinas → cidade errada

---

## Categorias do WordPress

Escolha **uma categoria principal** com base no tema do post.
Use o `wp_category_id` correspondente ao chamar `wp_publish.py create --category-id`.

| Tema do post | Categoria | wp_category_id |
|---|---|---|
| Show, concerto, festival de música | Música | 23 |
| Teatro, dança, circo, performance | Arte | 22 |
| Cinema, série, documentário | Audiovisual | 533 |
| Livro, leitura, autor, cordel, literatura | Literatura | 540 |
| Curso gratuito, oficina, palestra, workshop | Educação | 384 |
| Festa, carnaval, bloco | Carnaval | 561 (se carnaval) / Diversão 11 |
| Exposição, museu, galeria | Cultura | 13 |
| Evento misto / o que fazer no fim de semana | Rolês | 19 |
| Gastronomia, restaurante, feira de comida | Comida | 10 |
| Evento geral sem categoria específica | Eventos | 12 |

**Regra:** prefira a categoria mais específica. "Círculo do Livro" → Literatura (540), não Eventos (12).

---

## Saída esperada do Claude

Retorne um objeto JSON com os campos:

```json
{
  "relevante": true,
  "motivo_descarte": "",
  "categoria": "EVENTO FUTURO",
  "titulo": "Festival de Jazz chega a Americana em abril",
  "slug": "festival-jazz-americana-abril",
  "wp_category_id": 23,
  "html": "<p>...</p><h2>Serviço</h2><ul>...</ul>",
  "dados_ausentes": [],
  "credito_imagem": ""
}
```

Se `relevante` for `false`, preencha `motivo_descarte` e retorne os demais campos vazios.
