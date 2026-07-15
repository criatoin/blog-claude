# Revisão do sistema autônomo do +blog — Design

Data: 2026-07-15
Status: aprovado em brainstorming, aguardando revisão final do usuário

## Contexto e diagnóstico

O sistema autônomo (releases → WP rascunho → Telegram; pautas semanais; arte IG via Pillow)
roda em produção no Coolify, mas apresenta três falhas que impedem que ele funcione como
assistente real:

1. **Pautas fake**: `run_pauta_generate.py` pede ao DeepSeek para inventar 10 pautas sem
   nenhuma fonte real. O Tavily (`search_sources.py`) só é usado depois, na produção —
   ou seja, o sistema inventa primeiro e busca fontes depois. Alucinação por design.
2. **Legendas fracas/quebradas**: `llm_call_json()` não usa structured outputs — depende
   de ~80 linhas de reparo de JSON. Quando falha, um fallback genérico segue o pipeline
   como se fosse legenda pronta. Além disso, o DeepSeek-chat não sustenta a voz editorial
   em português criativo.
3. **Imagens com tipo errado**: a validação vision (Gemini) aceita imagem **sem validar**
   quando a API retorna 503; o score do `image_select.py` é puramente técnico (um flyer em
   alta resolução pontua bem); e o último fallback publica um placeholder cinza sólido.

Problemas menores: referência morta a `assets/instagram/6.jpg` (deletado); diagramação da
arte IG quebra títulos mecanicamente; Google Sheets não é usado pelo editor e adiciona
complexidade/OAuth à toa.

## Decisões (confirmadas com o usuário)

- Pautas: 100% baseadas em fontes reais (search-first). Pauta sem fonte = descartada.
- Modelo: híbrido — DeepSeek nas tarefas mecânicas, modelo criativo superior nas tarefas
  de escrita. Padrão `google/gemini-2.5-flash` via OpenRouter, trocável por env var.
- Imagens: sem foto confiável → gate humano no Telegram. Nada genérico publica sozinho.
- Legendas: manter os exemplos de voz atuais no prompt; o ganho vem do modelo melhor.
- Arte IG: o visual atual já segue a `referencia.png`; corrigir textos e diagramação.
- Google Sheets: **removido do sistema**.

## Abordagem escolhida

Revisão incremental focada (opção A): manter a arquitetura de scripts determinísticos +
validações + aprovação via Telegram, atacando cirurgicamente as frentes abaixo. Cada
frente é testável isolada e o sistema continua rodando durante a transição.

---

## Frente 1 — Pautas com fontes reais (search-first)

Arquivo principal: `execution/run_pauta_generate.py` (+ `search_sources.py`, `run_pauta_produce.py`)

Fluxo novo:

1. **Coleta determinística** (sem LLM): lista fixa de ~8–12 queries Tavily rodadas toda
   segunda — ex. "agenda cultural Americana SP", "eventos este fim de semana Santa Bárbara
   d'Oeste", "o que fazer Nova Odessa", "programação cultural Sumaré" — com filtro de
   recência (últimos 7 dias) e preferência pelos domínios já listados em
   `PREFERRED_DOMAINS` (prefeituras, portais locais). Resultado: ~30–50 achados reais
   (título, URL, trecho, data), deduplicados por URL.
2. **Curadoria pelo modelo criativo**: recebe os achados e agrupa em até 10 pautas.
   Schema exige campo `fontes: [urls]` — cada pauta deve citar as URLs de origem e só
   pode afirmar o que está nos trechos fornecidos.
3. **Validação determinística (anti-alucinação)**: toda URL citada é conferida contra o
   conjunto coletado. URL inventada ou pauta sem fonte → descartada. Se sobrarem 4, vão 4.
   Se sobrar zero, o Telegram avisa "nenhuma pauta com fonte confirmada esta semana".
4. **Card do Telegram**: cada pauta exibe o link da fonte para verificação rápida.
5. **Produção** (`run_pauta_produce.py`): recebe as URLs das fontes validadas e busca o
   conteúdo completo delas (Tavily extract ou requests) como matéria-prima do texto —
   em vez de buscar do zero por um título inventado.
6. GSC/GA continuam como critério de **priorização**, nunca como fonte de conteúdo.

Custo: ~10 buscas Tavily/semana (free tier: 1.000/mês).

## Frente 2 — Roteamento híbrido de modelos + JSON garantido

Arquivos: `execution/llm_call.py`, `execution/editorial.py`

Divisão por tarefa (env vars, sem mexer em código para trocar):

| Tarefa | Modelo | Env var |
|---|---|---|
| Extrair fatos, avaliar relevância, hierarquia, validar fatos | DeepSeek (atual) | `EDITORIAL_MODEL` |
| Legenda IG, texto da arte, HTML do post, curadoria de pautas | Modelo criativo | `CREATIVE_MODEL` (padrão `google/gemini-2.5-flash`) |

Se a voz não convencer após teste, sobe para `anthropic/claude-haiku-4.5` mudando só a
env var no Coolify.

JSON garantido:

1. `llm_call_json()` envia `response_format: {"type": "json_object"}` na chamada
   OpenRouter — JSON válido forçado pela API, não pedido no prompt.
2. Validação de campos obrigatórios pós-parse (ex.: `legenda_curta` e `legenda_contexto`
   não-vazios, com nº mínimo de blocos). Falhou → 1 retentativa com o erro no prompt.
   Falhou de novo → card do Telegram marca "⚠️ legenda precisa de revisão manual".
3. O reparo de JSON existente vira último recurso, não caminho comum.
4. **Fallback genérico nunca mais segue como conteúdo pronto** — fallback é sinalizado
   como pendência no card.

## Frente 3 — Pipeline de imagens com gate humano

Arquivos: `execution/run_releases.py`, `execution/image_generate.py`, `execution/telegram_bot.py`,
`execution/telegram_notify.py`

Regra: **nada genérico ou duvidoso é publicado sozinho.**

1. Fotos do release seguem com prioridade máxima (validação vision como hoje).
2. Vision indisponível (503) → imagem **não** é aprovada automaticamente; cai no fluxo
   de pendência (item 4). Muda o comportamento atual de "aceitar sem validar".
3. Placeholder cinza (`_try_pil_placeholder`): **eliminado**.
4. Sem foto aprovada → rascunho WP é criado sem imagem destacada e o card do Telegram
   traz "⚠️ Sem imagem adequada" + a melhor candidata de banco (Unsplash/Pexels) como
   sugestão, com botões `[Usar esta]` e `[Vou enviar foto]`:
   - `[Usar esta]`: bot sobe a sugestão para o WP, define como destacada, gera arte IG
     e reenvia o card completo para aprovação.
   - `[Vou enviar foto]`: bot aguarda uma foto respondida no chat, processa
     (crop/WebP via `image_process.py`), sobe para o WP, gera arte IG e reenvia o card.
5. Arte IG só é gerada com imagem aprovada — nunca com placeholder ou foto rejeitada.
6. Estado da pendência de imagem em `.tmp/pending_images.json` (mesmo padrão dos demais).

Estimativa: ~80% dos posts seguem 100% automáticos; o humano entra só nos casos-problema.

## Frente 4 — Arte IG: textos e diagramação

Arquivos: `execution/instagram_image.py`, `execution/run_releases.py`, `execution/editorial.py`

Causas atuais dos textos quebrados:

- `title.split()[:6]` trunca a 7ª palavra em diante silenciosamente;
- título <4 palavras recebe o nome da categoria colado no fim ("Sarau Ameriafro Cultura");
- quebra de linha por contagem de palavras (2+2, 3+2, 2+2+2) ignora largura real;
- badge fixo em y=720 e bloco de texto crescendo para baixo → colisão com o logo em
  títulos de 3 linhas + apoio de 2 linhas.

Design novo:

1. **Layout ancorado de baixo para cima**: calcula a altura total do bloco
   (badge + título + linha de apoio), posiciona acima do logo com respiro fixo.
   Sem colisão e sem texto flutuando.
2. **Quebra de linha por largura medida (balanced wrap)**: distribui palavras em 2–3
   linhas minimizando o desequilíbrio, via `textlength` do Pillow. Sem limite artificial
   de palavras — o limite é visual: cabe em ≤3 linhas com fonte ≥60pt.
3. **Preflight de renderização**: antes de aceitar o `titulo_principal` do LLM, medir se
   renderiza em ≤3 linhas com fonte ≥60pt. Não coube → retentativa ao modelo criativo com
   o motivo e o limite em caracteres; depois fallback determinístico. A validação por
   contagem de palavras (em `editorial.py` e `run_releases.py`) é removida.
4. **Sem truncamento e sem enchimento**: título curto é válido e renderiza maior.
   As duas gambiarras (corte em 6 palavras; colar categoria) somem.
5. Título e linha de apoio passam a ser gerados pelo modelo criativo (Frente 2).

## Frente 5 — Remoção do Google Sheets

Arquivos: `execution/sheets_read.py`, `execution/sheets_write.py` (removidos) e todos os
call sites (`run_releases.py`, `run_pauta_generate.py`, `run_pauta_produce.py`,
`telegram_bot.py`, `telegram_notify.py`, `start.sh`).

O Sheets cumpre hoje 3 papéis, substituídos assim:

1. **Dedup persistente de releases** → consulta ao próprio WordPress (existe post com
   este slug/título?) antes de criar rascunho. WP vira fonte única da verdade.
   O dedup local `.tmp/processed_emails.json` continua como cache rápido.
2. **Armazenamento de legendas IG** → já chegam no card do Telegram com a arte
   (de onde o editor copia na prática). Upload da arte ao WP Media continua.
3. **IDs de pauta para os botões [Produzir N]** → IDs do `.tmp/pending_pautas.json`.

Remover também as env vars `SHEETS_ID`/`GOOGLE_CLIENT_*`/`GOOGLE_REFRESH_TOKEN` da
documentação e do Coolify (Gmail usa credencial própria e continua).

## Frente 6 — Robustez e limpeza

1. Remover `IG_MODEL` (referência morta ao `6.jpg` deletado) em `run_releases.py` e
   `run_pauta_produce.py`.
2. Fallbacks silenciosos viram pendências visíveis: qualquer etapa que caiu em fallback
   marca o card do Telegram com ⚠️ e o motivo.
3. Diretivas atualizadas (`directives/pauta-semanal.md`, `release-to-post.md`,
   `social-instagram.md`, `image-select-resize.md`) para refletir o novo funcionamento.
4. **Smoke test**: `execution/smoke_test.py` roda o pipeline com um release de exemplo
   em modo local estendido (extrai fatos, gera conteúdo, legenda e arte — sem publicar,
   sem Telegram). Serve para validar mudanças futuras sem gastar release real.
   Testável com a foto "Oficina Efeitos especiais Americana SP.jpg".

## Tratamento de erros (transversal)

- Toda falha de API externa (Tavily, OpenRouter, Gemini, WP, Telegram) loga o erro e
  degrada para pendência visível — nunca para conteúdo genérico silencioso.
- Retentativas LLM: máximo 1 por etapa, sempre com o motivo da rejeição no prompt.
- Validações determinísticas continuam sendo a última linha (padrão atual, mantido).

## Testes

- `smoke_test.py` como verificação end-to-end local (Frente 6).
- Cada frente é verificável isolada:
  - F1: rodar `run_pauta_generate.py` e conferir que toda pauta tem URL real acessível.
  - F2: gerar 3 legendas com `CREATIVE_MODEL` e comparar com as atuais.
  - F3: simular release sem anexo e conferir card de pendência + fluxo de foto no Telegram.
  - F4: renderizar arte com títulos de 2, 5 e 9 palavras e conferir diagramação.
  - F5: rodar pipeline completo sem env vars do Sheets configuradas.

## Fora de escopo

- Publicação automática no Instagram (continua manual, via card do Telegram).
- Redesign visual da arte (o template atual já segue a `referencia.png`).
- Mudanças no WordPress/tema/SEO on-page.
- Migração de infraestrutura (continua Coolify, container único, cron interno).

## Ordem de implementação sugerida

1. Frente 2 (modelos + JSON) — base para todas as outras.
2. Frente 4 (arte) — depende do modelo criativo.
3. Frente 3 (imagens + gate Telegram).
4. Frente 1 (pautas search-first).
5. Frente 5 (remoção do Sheets).
6. Frente 6 (limpeza, diretivas, smoke test).
