# Diretiva — Geração de Pauta Semanal +blog

## Objetivo
Gerar 10 sugestões de pauta com base em dados reais (GSC + GA4), datas sazonais
e necessidades editoriais do portal, priorizando temas com evidência de demanda.

---

## Identidade editorial (lembre sempre)

O +blog cobre **cultura e diversão** de Americana, Santa Bárbara d'Oeste (SBO),
Nova Odessa e Sumaré. Pauta fora dessas cidades ou fora desses temas → descartar.

---

## Fontes de dados usadas

| Script | O que retorna | Para que serve |
|--------|---------------|----------------|
| `gsc_report.py` | Queries com impressões > 50 e CTR < 3% | Temas que as pessoas buscam mas o site não responde bem |
| `ga_report.py` | Top 10 posts mais visitados (30d) | Temas em alta que devem ganhar conteúdo complementar |
| `search_sources.py` | Fontes da web sobre o tema | Embasar a pauta com dados verificáveis |

---

## Processo de geração

### 1. Cruzar dados GSC × GA

Para cada query do GSC com alto volume e baixo CTR:
- Há post no site sobre este tema? (verifique nos dados do GA)
- Se não há post → oportunidade de criar conteúdo novo
- Se há post com muitas visitas → oportunidade de atualizar / aprofundar

### 2. Adicionar contexto sazonal

Considere datas e eventos próximos à semana de publicação:
- Carnaval (fevereiro/março), Festas Juninas (junho/julho)
- Dia das Mães, Dia dos Namorados, Natal
- Eventos recorrentes da região (Expo Americana, Mercado Municipal de SBO)
- Feriados municipais das 4 cidades

### 3. Gerar 10 sugestões

Para cada sugestão, determine:

| Campo | Descrição |
|-------|-----------|
| `titulo` | Título SEO em até 65 caracteres (cidade + tema) |
| `keyword` | Query principal do GSC ou tema do GA |
| `categoria` | Uma das categorias do WordPress (ver tabela abaixo) |
| `justificativa` | Dado de evidência: "GSC: 1.2k impressões, CTR 1.8%" ou "GA: 3.4k views/mês" |
| `slug_sugerido` | slug em lowercase, sem acento, com hífens |

### Categorias do WordPress

| Tema | Categoria | wp_category_id |
|------|-----------|----------------|
| Show, concerto, festival de música | Música | 23 |
| Teatro, dança, circo, performance | Arte | 22 |
| Cinema, série, documentário | Audiovisual | 533 |
| Livro, leitura, autor | Literatura | 540 |
| Curso gratuito, oficina, palestra | Educação | 384 |
| Festa, carnaval, bloco | Diversão | 11 |
| Exposição, museu, galeria | Cultura | 13 |
| Evento misto / fim de semana | Rolês | 19 |
| Gastronomia, restaurante, feira | Comida | 10 |
| Evento geral | Eventos | 12 |

---

## Tipos de pauta — misture sempre

| Tipo | Descrição | Exemplo |
|------|-----------|---------|
| Agenda | O que fazer no fim de semana / na semana | "5 opções de lazer grátis em Americana neste fim de semana" |
| Lista | Compilação temática | "Melhores teatros em Santa Bárbara d'Oeste" |
| Matéria explicativa | Explica um tema com contexto | "O que é o Círculo do Livro e como funciona em SBO" |
| Retrospectiva | Balanço de evento passado | "Como foi a primeira noite do Festival de Jazz de Americana" |
| Antevisão | Prévia de evento futuro | "Tudo que você precisa saber sobre a Virada Cultural de Sumaré" |

---

## Regras obrigatórias

1. **Nunca gere pauta sem antes buscar fontes** com `search_sources.py`
2. **Se Tavily retornar `sufficient: false`** → marque a pauta como `Sem fontes` e não a produza
3. **Máximo 3 pautas do mesmo tipo** numa mesma semana (diversificar formatos)
4. **Citar fontes no final do post** com as URLs retornadas pelo Tavily
5. **Priorizar pautas com dado de evidência** (GSC ou GA) sobre intuição editorial

---

## Saída esperada do Claude

Retorne um array JSON com 10 objetos:

```json
[
  {
    "id": 1,
    "titulo": "O que fazer em Americana neste fim de semana",
    "keyword": "o que fazer americana",
    "categoria": "Rolês",
    "wp_category_id": 19,
    "justificativa": "GSC: 320 impressões, CTR 1.2% — demanda real sem conteúdo recente",
    "slug_sugerido": "o-que-fazer-americana-fim-de-semana",
    "tipo": "Agenda"
  },
  ...
]
```

---

## Produção da pauta escolhida

Quando o usuário escolher uma pauta para produzir:

1. Buscar fontes: `search_sources.py --query "<keyword> <cidade>"`
2. Se `sufficient: false` → informar usuário, marcar como "Sem fontes", parar
3. Escrever o post usando `directives/release-to-post.md` como guia de tom/estrutura
4. Citar as fontes ao final do HTML:
   ```html
   <p><em>Fontes: <a href="URL1">Título1</a>, <a href="URL2">Título2</a></em></p>
   ```
5. Seguir pipeline de imagem → Instagram → WP → Sheets → Telegram (igual ao release)
