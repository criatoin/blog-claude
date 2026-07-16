# Diretiva — Geração de Pauta Semanal +blog

## Objetivo
Gerar até 10 sugestões de pauta **exclusivamente a partir de achados reais da web**
(busca Tavily), usando GSC + GA4 apenas como critério de priorização — nunca como
fonte de invenção. Implementado em `execution/run_pauta_generate.py`.

**Não há mais planilha Google Sheets nesse fluxo.** O estado da semana vive em
`.tmp/pautas_semana.json` e a lista é enviada direto ao Telegram.

---

## Identidade editorial (lembre sempre)

O +blog cobre **cultura e diversão** de Americana, Santa Bárbara d'Oeste (SBO),
Nova Odessa e Sumaré. Pauta fora dessas cidades ou fora desses temas → descartar.

---

## Fluxo search-first (como funciona hoje)

1. **Coleta determinística** — `search_sources.py` roda para 10 queries fixas
   (cobrindo as 4 cidades + agenda regional), sempre com janela de **7 dias**.
   Os resultados de todas as queries são deduplicados por URL em um pool de
   "achados" (título, URL, snippet).
2. **Se nenhum achado** vier de nenhuma query → o script **não inventa pauta
   nenhuma**. Envia um aviso `⚠️ Pautas da semana: nenhuma fonte encontrada na
   web` ao Telegram e encerra. Zero pautas é um resultado válido e esperado.
3. **Priorização opcional** — `gsc_report.py` (queries com volume/CTR) e
   `ga_report.py` (posts mais lidos) são anexados ao prompt de curadoria só
   para ordenar por potencial de busca. Se qualquer um falhar, a curadoria
   segue sem eles (não bloqueia o fluxo).
4. **Curadoria via `CREATIVE_MODEL`** — o modelo agrupa os achados reais em
   até 10 sugestões de pauta. Regra absoluta do prompt: cada pauta deve citar
   em `fontes` as URLs **literais** dos achados que a embasam; o modelo nunca
   deve inventar evento, data, local ou atração fora do que está nos trechos.
5. **Validação anti-alucinação (determinística)** — `validar_pautas()` remove
   qualquer URL citada que não esteja no conjunto de achados coletados. Uma
   pauta que fique sem nenhuma fonte válida após esse filtro é **descartada**,
   mesmo que o modelo a tenha proposto. Se a curadoria não render nenhuma
   pauta válida → aviso `⚠️ nenhuma pauta com fonte confirmada. Nada foi
   inventado.` ao Telegram, sem fallback ou invenção.
6. **Saída** — `.tmp/pautas_semana.json` guarda o registro completo (título,
   keyword, categoria, justificativa, tipo, fontes com title/url/snippet) por
   `pauta_id`. O Telegram recebe a lista numerada com o link da primeira fonte
   ao lado de cada título (`send-pauta-list`).

**Regra de ouro:** pauta sem fonte real coletada nesta mesma rodada = pauta
descartada. Nunca criar pauta "de memória" ou "de intuição editorial" sem
achado que a sustente.

---

## Campos de cada pauta

| Campo | Descrição |
|-------|-----------|
| `titulo` | Título SEO em até 65 caracteres (cidade + tema) |
| `keyword` | Query principal usada na busca/priorização |
| `categoria` | Uma das categorias do WordPress (ver tabela abaixo) |
| `wp_category_id` | ID da categoria WordPress correspondente |
| `justificativa` | Por que a pauta importa (dado de GSC/GA quando houver, ou relevância editorial) |
| `tipo` | Agenda / Lista / Explicativa / Retrospectiva / Antevisão |
| `fontes` | Lista de URLs reais coletadas pelo Tavily que embasam a pauta (obrigatório) |

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

1. **Nunca gere pauta sem achado real coletado nesta mesma rodada** de
   `search_sources.py` (10 queries fixas, janela de 7 dias).
2. **Pauta sem URL válida no conjunto de achados** → descartada por
   `validar_pautas()`, mesmo que o modelo a tenha sugerido.
3. **Zero achados ou zero pautas válidas** → aviso `⚠️` ao Telegram, script
   encerra sem produzir nada. Nunca preencher a lista com pautas inventadas.
4. **Máximo 3 pautas do mesmo tipo** numa mesma semana (diversificar formatos).
5. **GSC/GA entram só como priorização** (ordenar por potencial de busca),
   nunca como fonte de fato — se indisponíveis, o fluxo segue sem eles.

---

## Saída do gerador (`run_pauta_generate.py`)

`.tmp/pautas_semana.json` — dict indexado por `pauta_id` (string "1".."10"):

```json
{
  "1": {
    "titulo": "O que fazer em Americana neste fim de semana",
    "keyword": "o que fazer americana",
    "categoria": "Rolês",
    "wp_category_id": 19,
    "justificativa": "Feira de artesanato e show gratuito confirmados para sábado",
    "tipo": "Agenda",
    "fontes": [
      {"title": "Prefeitura anuncia feira...", "url": "https://...", "snippet": "..."}
    ]
  }
}
```

O Telegram recebe a lista numerada (`send-pauta-list`) com o link da primeira
fonte ao lado de cada título, e cada item tem um botão `[Produzir N]`.

---

## Produção da pauta escolhida (`run_pauta_produce.py --pauta-id N`)

Quando o operador aciona `[Produzir N]` no Telegram:

1. Lê a pauta e suas `fontes` já coletadas em `.tmp/pautas_semana.json`.
2. Faz **uma busca complementar** (`search_sources.py`, até 3 resultados) para
   enriquecer o conjunto de fontes antes de escrever.
3. Se, mesmo assim, não houver nenhuma fonte → avisa `⚠️` ao Telegram e
   cancela (não deveria acontecer, pois a geração já validou fontes).
4. Escreve o post completo via `CREATIVE_MODEL`, citando os links das fontes
   no HTML (`<p><em>Fontes: <a href="url">título</a></em></p>`).
5. Gera imagem de capa (`image_generate.py`), arte Instagram
   (`instagram_image.py`) e legenda (`CREATIVE_MODEL`).
6. Cria o rascunho no WordPress (`wp_publish.py create`).
7. Envia o card ao Telegram (`send-release`) — **sem Google Sheets**: a
   legenda do Instagram já vai embutida no próprio card.
