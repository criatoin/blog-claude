# Checador de Fatos com Jev + DeepSeek V4 — registro (2026-10-06)

**Objetivo:** ter CERTEZA de que as matérias seguem o release. O LLM só escreve; a verificação é feita por código determinístico e pelo Jev. Substitui o antigo `validar_fatos` (LLM checando LLM, aprovava quando a API falhava e só lia 2000/3000 caracteres).

**Resultado:** implementado, testado (55 testes) e em produção desde 16:54 BRT. Deploy `ylbeb49jtw57r4dczbfuaoi7` no Coolify (serviço `blog-telegram-bot`), commit `4ff4f635` da `main`.

## Como funciona

- `execution/fact_check.py` — duas camadas, nenhuma com LLM gerador:
  1. **Código:** datas, horários, valores (R$), telefones, links, e-mails, @perfis e "gratuito" citados na matéria precisam existir no release. Formatos diferentes do mesmo dado são normalizados (19h30 = 19:30, "4 de maio" = 04/05).
  2. **Jev** (TypeSafe, via OpenRouter `POST /api/alpha/decisions`, modelo `~typesafe/jev-latest`, mesma `OPENROUTER_API_KEY`): cada frase da matéria, do título, do subtítulo, do resumo, da arte e da legenda é classificada contra o release — `supported`, `contradicted`, `mixed`, `insufficient_evidence` ou `opinion`.
  - Risco = soma das probabilidades de `contradicted` + `mixed` + `insufficient_evidence`: ≥ 0,6 bloqueia; entre 0,3 e 0,6 vira alerta.
  - **Fail-closed:** se o Jev não responder, o status é `incompleto`, nunca `aprovado`.
- `execution/editorial_checagem.py` — `checar_e_corrigir`: se há problema em título, subtítulo, resumo ou HTML, o modelo criativo corrige só aqueles trechos e a matéria é checada de novo, até 2 vezes. HTML com menos da metade do tamanho original é rejeitado. Problemas na arte ou na legenda do Instagram não são reescritos: viram alerta no card. Também define o novo `resumo_telegram`.
- `execution/run_releases.py` — passo 6 chama `checar_e_corrigir` antes de criar o rascunho no WordPress.
- `execution/telegram_notify.py` — o card mostra a linha `✅ Checagem: N frases conferidas…`, `⛔ Checagem: N problema(s) não corrigido(s)…` ou `⚠️ Checagem incompleta…`.
- `execution/llm_call.py` — `CREATIVE_MODEL` padrão `deepseek/deepseek-v4-pro`, com `reasoning.enabled=false` para modelos `deepseek/deepseek-v4*` e `TIMEOUT_SECS=120`.
- `crontab` — geração semanal de pautas desativada (sugestões de baixa qualidade). Para religar, descomentar a linha.
- Env opcionais: `JEV_MODEL` (padrão `~typesafe/jev-latest`), `JEV_WORKERS` (padrão 6). Teste manual: `python execution/fact_check.py --release-file R.txt --post-file P.json`.

## Medições

- Jev: 21/21 em PT-BR contra releases reais (datas, horários, preço, local, nomes, informação inventada, opinião); ~2 s e ~US$ 0,00004 por frase. A categoria extra `opinion` é necessária: sem ela, opinião editorial e informação inventada caem ambas em `insufficient_evidence`.
- DeepSeek V4 pro: 16 s por texto sem raciocínio contra 32–95 s com raciocínio. Por isso o raciocínio foi desligado e o timeout subiu de 60 para 120 s.
- Matéria real do MAC escrita pelo V4: o Jev pegou "inspirou os k-dramas" (o release não diz isso); o redator corrigiu sozinho. `checar_e_corrigir` levou ~90 s e custou US$ 0,0013.

## Decisões e desvios

- O laço de correção ficou em `editorial_checagem.py` e o `editorial.py` ficou **intacto**: o arquivo tem 45 KB com prompts longos, e reenviá-lo inteiro pelo conector do GitHub arriscava alterar os prompts de produção. Consequência: `validar_fatos` e o `resumo_telegram` antigo seguem em `editorial.py` como código sem uso.
- `CREATIVE_MODEL` mudou no código, não nas variáveis do Coolify. Se a variável for definida lá, ela sobrescreve o padrão.
- "Bloqueado" não impede o rascunho: toda matéria vira rascunho no WordPress e só é publicada pelo botão do Telegram.

## Infra

- Criado volume persistente `blog-tmp` em `/app/.tmp` (antes o serviço não tinha volume e todo redeploy zerava `pending_approvals`, `processed_emails` e `telegram_offset`).
- O deploy terminou antes do cron das 17h, com `processed_emails.json` vazio: possível reprocessamento de e-mails do dia (rascunhos e cards duplicados a descartar). Regra para os próximos deploys: depois das 18h BRT (o cron só roda de seg a sex, das 8h às 18h) ou com o volume já populado.
- O Coolify não tem webhook do GitHub: `push` não dispara deploy.

## Git

Os tokens do GitHub (URL do remote e memória) estavam inválidos (401), então os arquivos subiram pelo conector do GitHub desta sessão. O histórico local diverge do remoto, com o mesmo conteúdo (19 arquivos de `execution/` conferidos byte a byte por hash). Para reconciliar com credencial nova: `git stash` → `git fetch origin && git reset --hard origin/main` → `git stash pop`.

## Limitações conhecidas

- Erro factual na arte do Instagram não é reescrito (a arte é renderizada antes da checagem): vira alerta no card.
- Dedup por slug no WordPress é fraco com o V4 (slugs variam); a proteção real é o `processed_emails.json`, agora persistente.
- O endpoint do Jev é `alpha` e pode mudar. Se mudar, a checagem cai em `incompleto` (⚠️ no card), nunca em aprovado.
- `checar_e_corrigir` leva cerca de 90 s por matéria.
