# Diretiva — Legenda e Arte para Instagram +blog

## Objetivo
Produzir legenda e arte para o Instagram do +blog a partir de um post já escrito,
mantendo o tom do portal e maximizando o engajamento local.
Implementado em `execution/editorial.py` (`gerar_legenda`, `gerar_arte_com_validacao`)
e `execution/instagram_image.py` (composição Pillow).

**Sem Google Sheets:** a legenda de cada post vai embutida diretamente no card
do Telegram (`send-release` com `--ig-caption`), não é mais salva numa aba
separada.

---

## Identidade Instagram do +blog

**Canal:** portal de cultura e diversão de Americana, SBO, Nova Odessa e Sumaré.
**Público:** morador da região, 20–45 anos, curioso sobre a agenda local.
**Tom:** direto, convidativo, levemente informal. Sem juridiquês, sem corporativês, sem emoji excessivo.

---

## Estrutura da Legenda (gerada por `gerar_legenda`, sem hashtags)

A legenda tem **voz editorial de amigo da cidade**, não é um template de
blocos fixos de gancho/serviço/CTA/hashtags. `gerar_legenda()` produz duas
versões:

- `legenda_curta` — **3 a 4 blocos**, para posts mais urgentes.
- `legenda_contexto` — **5 a 6 blocos**, versão completa com mais contexto e
  CTA duplo (social + site).

Cada bloco é um parágrafo curto separado por linha em branco (`\n\n`) — nunca
um único parágrafo corrido.

**O que toda legenda deve ter:**
- Abertura que situa a cidade e o evento e prende a atenção, sem clichê de
  release ("o evento conta com...", "a programação prevê...").
- Detalhes concretos do release/post: atrações, data, local, horário,
  gratuidade — nunca inventados.
- Uma frase sobre por que o evento importa para quem mora na região.
- CTA social natural (marcar amigo, contar quem vai, salvar) e um CTA curto
  para o site (variando a frase, sem repetir sempre "link na bio").
- No máximo 1 emoji, só se encaixar naturalmente — nunca forçado.

**Proibido, em qualquer bloco:**
- Hashtags (`#`) — **o portal não usa mais hashtags nas legendas**. Tanto
  `legenda_curta` quanto `legenda_contexto` são validadas programaticamente
  (`_valida_legenda`) e rejeitam qualquer `#`.
- Palavras de assessoria/clichê: "imperdível", "confira", "experiência
  mágica", "incrível", "não perca", "vem aí", "prepare-se para".
- Aberturas artificiais genéricas ("voando alto", "magia da leitura",
  "mergulhe em" etc. — lista de bloqueio em `editorial.py`).
- Repetir mecanicamente o texto da arte (título/linha de apoio) — a legenda
  complementa, não copia.

Se a geração via LLM falhar a validação (hashtag, clichê, poucos blocos,
abertura artificial), o sistema tenta de novo; se ainda assim falhar, aplica
um fallback textual genérico e marca `_fallback` no resultado (aparece como
`⚠️` no card do Telegram — ver `directives/release-to-post.md`).

**Exemplo real de tom (referência de voz, não copiar literalmente):**
> "Americana vai ter sarau, cultura afro-brasileira e programação gratuita
> ocupando a Estação Cultura.
>
> No dia 16 de maio, o 1º Sarau Ameriafro reúne música, poesia, hip hop,
> capoeira, dança, grafite, maracatu e artistas da região em uma tarde de
> encontro, troca e presença.
>
> É aquele tipo de rolê que merece entrar na agenda: gratuito, diverso e com
> cara de cidade viva.
>
> Já marca aqui quem vai colar com você.
>
> A programação completa, com horários e atrações, está no +blog."

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
  --category "{nome_da_categoria}" \
  --subtitle "{linha_apoio}"
```

O script usa composição local via Pillow (sem API externa, sem imagem de
referência fixa em `assets/instagram/`):
1. Fundo escuro sólido cobre todo o canvas (compatível com foto horizontal ou
   vertical, sem mancha de blur).
2. A foto de capa do post é a camada principal, com degradê nos últimos 200px.
3. Badge de categoria + título + linha de apoio são desenhados diretamente
   pelo script, **ancorados acima do logo** (bloco de texto posicionado a
   40px de respiro acima do topo do logo, não em posição fixa no canvas).
4. Logo circular do +blog (`assets/logo/Logo +blog rosa.png`, máscara remove
   fundo branco) fica sempre na base, centralizado.

### Validação do título (`title_fits` — preflight visual, não contagem de palavras)

O título da arte **não é mais validado por número de palavras**. Antes de
compor a imagem, `editorial.py` chama `instagram_image.title_fits(titulo)`,
que faz um preflight de renderização real:

- Tenta encaixar o título em **até 3 linhas** (`TITLE_MAX_LINES = 3`),
  testando tamanhos de fonte decrescentes de 92pt até um mínimo de **60pt**
  (`TITLE_SIZE_MAX`/`TITLE_SIZE_MIN`), com `_balanced_wrap` buscando a quebra
  mais equilibrada entre linhas.
- Se nenhum tamanho de fonte ≥60pt encaixa o título em 3 linhas, `title_fits`
  retorna `(False, motivo)` e `gerar_arte_com_validacao` trata isso como erro
  crítico do `texto_arte` — o LLM é acionado de novo com o motivo exato como
  feedback ("título não cabe em 3 linhas com fonte mínima 60pt — encurte para
  até ~70 caracteres"), e só então (se ainda falhar) o fallback determinístico
  entra em ação.
- Isso substitui a regra antiga de "máximo 6 palavras": o critério real é
  **caber visualmente na arte**, então um título de 5 palavras longas pode
  falhar e um de 8 palavras curtas pode passar.

Após gerar a arte, fazer upload para WP Media Library para obter URL pública:
```bash
python execution/wp_publish.py upload-image \
  --image-path ".tmp/{slug}_ig.webp" \
  --title "{titulo} — Instagram"
```
A URL retornada (`url`) é usada apenas para publicação manual/posterior no
Instagram — **não há mais planilha Google Sheets** guardando esse caminho; a
arte e a legenda chegam juntas no card do Telegram (`send-release`).

Se o script de composição falhar, use a imagem da capa como arte de Instagram
mesmo (fallback de última instância, sem bloquear o rascunho).

---

## Saída esperada do LLM (`gerar_arte_com_validacao` → `texto_arte`)

```json
{
  "template": "ameriafro_v3",
  "badge": "MÚSICA",
  "titulo_principal": "Festival de Jazz no Parque Urbano",
  "linha_apoio": "Sábado, 19h, entrada gratuita em Americana",
  "alerta": ""
}
```

A legenda (`gerar_legenda` → `legenda_curta` / `legenda_contexto`) é um
objeto separado — ver seção "Estrutura da Legenda" acima. Ambos os campos vão
juntos no card do Telegram, sem passar por planilha.

---

## Regras gerais

- Nunca inventar data, local ou valor que não esteja no release/post
- `titulo_principal` não pode ser igual a `titulo_site`, nem conter ponto
  final, hashtag ou palavras proibidas ("imperdível", "confira", "não
  perca", "vem aí", "promete", "acontece em")
- `linha_apoio` deve caber em uma linha (máx ~60 caracteres no total)
- A legenda deve ser autossuficiente — o leitor não precisa clicar para entender o evento
- Não repetir o título do post na legenda palavra por palavra — reformule o gancho
