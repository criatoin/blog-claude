# Editorial Upgrade — Pipeline de Releases

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir as 3 funções LLM internas de `run_releases.py` pelo módulo `editorial.py` com 6 funções que extraem fatos, avaliam relevância com scores, geram conteúdo com voz editorial fixa, produzem legenda IG com CTAs rotativos, validam facticidade e montam resumo para o Telegram — tudo sem alterar infraestrutura (WP, Sheets, imagens, bot).

**Architecture:** Novo módulo `execution/editorial.py` encapsula toda lógica LLM editorial; `run_releases.py` importa e chama essas funções em sequência dentro de `processar_email()`; `telegram_notify.py` recebe `--card-meta` JSON para exibir scores; `instagram_image.py` aceita `--art-title`/`--art-subtitle` opcionais; `sheets_write.py` ganha coluna `legenda_longa` na aba Legendas IG.

**Tech Stack:** Python 3.11, `llm_call.py` (OpenRouter), Pillow (inalterado), Google Sheets API, Telegram Bot API, `python-dotenv`

---

## Mapa de arquivos

| Arquivo | Ação | Responsabilidade |
|---------|------|-----------------|
| `execution/editorial.py` | **Criar** | 6 funções LLM editoriais + voz editorial fixa |
| `execution/run_releases.py` | **Modificar** | Trocar `_llm_relevancia`, `_llm_reescrever`, `_llm_legenda_ig` pelas funções do editorial; adaptar `_pipeline_imagem` para usar `_query_from_fatos`; passar `--card-meta` ao Telegram |
| `execution/telegram_notify.py` | **Modificar** | Argumento `--card-meta` em `send-release`; novo formato do card com scores e alertas |
| `execution/instagram_image.py` | **Modificar** | Args opcionais `--art-title` e `--art-subtitle` |
| `execution/sheets_write.py` | **Modificar** | Coluna `legenda_longa` na aba Legendas IG; gravar `legenda_contexto` nessa coluna |

---

## Task 1: Criar `execution/editorial.py` — esqueleto + modelo

**Files:**
- Create: `execution/editorial.py`

- [ ] **Step 1: Criar o arquivo com EDITORIAL_MODEL e a voz editorial**

```python
"""
editorial.py — Funções LLM editoriais do pipeline de releases.

Todas as funções usam EDITORIAL_MODEL (configurável por env var).
Fallbacks conservadores: nunca bloqueiam o pipeline.
"""

import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()

EDITORIAL_MODEL = os.getenv("EDITORIAL_MODEL", "deepseek/deepseek-chat")

_VOZ_EDITORIAL = """
Você é o editor assistente do +blog, portal regional de cultura, diversão e vida nas cidades
de Americana, Santa Bárbara d'Oeste, Nova Odessa e Sumaré.

Sua função é transformar informações confirmadas em conteúdo com linguagem leve, local, útil
e compartilhável. O +blog não escreve como assessoria de imprensa.

Tom: leve, claro, regional, informativo sem ser duro, próximo sem exagerar na informalidade,
positivo e comunitário, frases curtas, sem sensacionalismo, sem parecer propaganda.

Evite: "o evento promete", "imperdível" em excesso, "confira" repetidamente, linguagem
institucional, copiar a ordem do release, títulos longos, hashtags genéricas, "evento acontece em...".

Priorize: benefício para o público, cidade logo no início quando relevante, se é gratuito /
quando / onde / para quem, gancho humano ou cultural, título com curiosidade ou pertencimento.

REGRA FACTUAL OBRIGATÓRIA: afirme apenas informações presentes no release original ou no
JSON de fatos. Nunca invente datas, horários, locais, atrações, preços, cidades, links ou
formas de inscrição.
""".strip()
```

- [ ] **Step 2: Commitar o esqueleto**

```bash
git add execution/editorial.py
git commit -m "feat: cria editorial.py — esqueleto com EDITORIAL_MODEL e voz editorial"
```

---

## Task 2: `editorial.py` — Função 1: `extrair_fatos`

**Files:**
- Modify: `execution/editorial.py`

- [ ] **Step 1: Adicionar `extrair_fatos` ao arquivo**

Adicionar após o bloco `_VOZ_EDITORIAL`:

```python
def extrair_fatos(release_text: str) -> dict:
    """
    Extrai fatos estruturados do release.
    Fallback: dict com todos os campos vazios se LLM falhar.
    """
    from llm_call import llm_call_json

    _FATOS_VAZIOS = {
        "cidade": "", "local": "", "endereco": "", "data": "", "horario": "",
        "periodo": "", "valor": "", "gratuito": None, "inscricao_necessaria": None,
        "link_inscricao": "", "atracoes": [], "artistas": [], "projeto": "",
        "instituicao_realizadora": "", "publico_alvo": "", "categoria_editorial": "",
        "resumo_factual": "", "informacoes_ausentes": [], "observacoes": [],
        "creditos_texto": "", "creditos_fotos": "",
    }

    system = """Você é um extrator de fatos precisos. Leia o release e extraia APENAS informações explicitamente presentes no texto. Nunca infira nem complete dados ausentes.

Retorne APENAS um objeto JSON com exatamente estes campos:
{
  "cidade": "cidade principal do evento/notícia ou vazia se ausente",
  "local": "nome do local/venue ou vazio",
  "endereco": "endereço completo ou vazio",
  "data": "data(s) do evento em linguagem natural ou vazia",
  "horario": "horário(s) ou vazio",
  "periodo": "período de realização (ex: 'de maio a junho') ou vazio",
  "valor": "preço/ingresso em texto ou vazio",
  "gratuito": true/false/null (null = não mencionado no release),
  "inscricao_necessaria": true/false/null (null = não mencionado),
  "link_inscricao": "URL de inscrição ou vazio",
  "atracoes": ["lista de atrações, shows, atividades citadas"],
  "artistas": ["lista de artistas/performers citados pelo nome"],
  "projeto": "nome do projeto/evento ou vazio",
  "instituicao_realizadora": "organização realizadora ou vazia",
  "publico_alvo": "público-alvo mencionado ou vazio",
  "categoria_editorial": "categoria sugerida: Música|Arte|Audiovisual|Literatura|Educação|Diversão|Cultura|Rolês|Comida|Eventos",
  "resumo_factual": "resumo de 1-2 frases apenas com fatos confirmados",
  "informacoes_ausentes": ["lista de informações esperadas mas ausentes no release"],
  "observacoes": ["alertas editoriais relevantes"],
  "creditos_texto": "autor, assessoria, MTb ou organização remetente citados como fonte do texto",
  "creditos_fotos": "crédito de fotos/imagens mencionado no release ou vazio"
}"""

    try:
        result = llm_call_json(system=system, user=release_text[:6000], model=EDITORIAL_MODEL)
        if isinstance(result, dict):
            # Garante que todos os campos existam
            return {**_FATOS_VAZIOS, **result}
        return _FATOS_VAZIOS
    except Exception as e:
        print(f"[editorial] extrair_fatos falhou: {e}", file=sys.stderr)
        return _FATOS_VAZIOS
```

- [ ] **Step 2: Commitar**

```bash
git add execution/editorial.py
git commit -m "feat: editorial.py — extrair_fatos (função 1)"
```

---

## Task 3: `editorial.py` — Função 2: `avaliar_relevancia`

**Files:**
- Modify: `execution/editorial.py`

- [ ] **Step 1: Adicionar `avaliar_relevancia`**

```python
def avaliar_relevancia(release_text: str, fatos: dict) -> dict:
    """
    Avalia relevância editorial com scores numéricos.
    Fallback conservador: relevante=False para não bloquear o pipeline.
    """
    from llm_call import llm_call_json

    _FALLBACK = {
        "relevante": False,
        "cidade": "",
        "categoria_editorial": "",
        "relevancia_editorial": 0,
        "potencial_google": 0,
        "potencial_instagram": 0,
        "potencial_compartilhamento": 0,
        "urgencia": 0,
        "formato_ideal": "",
        "angulo_recomendado": "",
        "motivo_aprovacao_ou_descarte": "Erro na avaliação",
        "observacao_para_editor": "",
    }

    system = """Você é o editor-chefe do +blog, portal de cultura e diversão de Americana, Santa Bárbara d'Oeste, Nova Odessa e Sumaré (região de Campinas, SP).

Avalie se este release deve ser publicado no +blog. Considere:
1. Tem relação com Americana, SBO, Nova Odessa ou Sumaré?
2. Tem valor para moradores da região?
3. Tem apelo cultural, social, educativo, turístico, gastronômico, comunitário ou de lazer?
4. Pode gerar clique no site?
5. Pode gerar compartilhamento no Instagram?
6. É conteúdo útil, interessante ou relevante para a comunidade?

NÃO PUBLICAR: obras públicas, saúde, saneamento, política, administração municipal, esporte profissional sem relação com entretenimento, outras cidades sem relação regional, propaganda comercial pura.

Retorne APENAS um objeto JSON:
{
  "relevante": true/false,
  "cidade": "cidade principal identificada",
  "categoria_editorial": "Música|Arte|Audiovisual|Literatura|Educação|Diversão|Cultura|Rolês|Comida|Eventos",
  "relevancia_editorial": 0-10,
  "potencial_google": 0-10,
  "potencial_instagram": 0-10,
  "potencial_compartilhamento": 0-10,
  "urgencia": 0-10,
  "formato_ideal": "matéria|agenda|lista|retrospectiva|antevisão",
  "angulo_recomendado": "instrução editorial de 1 frase — qual ângulo explorar no texto",
  "motivo_aprovacao_ou_descarte": "motivo em 1 frase",
  "observacao_para_editor": "observação opcional para o editor humano"
}"""

    user = f"""Fatos extraídos:
{json.dumps(fatos, ensure_ascii=False, indent=2)}

Release original (primeiros 3000 chars):
{release_text[:3000]}"""

    try:
        result = llm_call_json(system=system, user=user, model=EDITORIAL_MODEL)
        if isinstance(result, dict) and "relevante" in result:
            return result
        return _FALLBACK
    except Exception as e:
        print(f"[editorial] avaliar_relevancia falhou: {e}", file=sys.stderr)
        return _FALLBACK
```

- [ ] **Step 2: Commitar**

```bash
git add execution/editorial.py
git commit -m "feat: editorial.py — avaliar_relevancia com scores (função 2)"
```

---

## Task 4: `editorial.py` — Função 3: `gerar_conteudo`

**Files:**
- Modify: `execution/editorial.py`

- [ ] **Step 1: Adicionar `gerar_conteudo`**

```python
def gerar_conteudo(release_text: str, fatos: dict, avaliacao: dict, sender: str = "") -> dict:
    """
    Gera o conteúdo editorial completo do post.
    Retorna dict com todos os campos ou campos vazios em caso de falha.
    sender: usado como fallback para creditos_wordpress.texto.
    """
    from llm_call import llm_call_json

    angulo = avaliacao.get("angulo_recomendado", "")
    angulo_instrucao = f"ÂNGULO EDITORIAL: {angulo}\n\n" if angulo else ""

    system = f"""{angulo_instrucao}{_VOZ_EDITORIAL}

════════════════════════════════
HTML PURO — PROIBIDO USAR MARKDOWN
════════════════════════════════
O campo "html" deve conter APENAS tags HTML válidas. Nunca use Markdown.
Use: <p>, <h2>, <strong>, <em>, <ul>, <li>
Mínimo: 400 palavras de conteúdo rico.

════════════════════════════════
ESTRUTURA DO POST
════════════════════════════════
- Abra com gancho forte (1 frase que prende)
- Desenvolva com contexto, detalhes e citações do release
- Feche com bloco Serviço (<h2>Serviço</h2> + <ul>) para eventos

════════════════════════════════
CATEGORIAS WORDPRESS
════════════════════════════════
Música: 23 | Arte: 22 | Audiovisual: 533 | Literatura: 540
Educação: 384 | Diversão: 11 | Cultura: 13 | Rolês: 19
Comida: 10 | Eventos: 12

Retorne APENAS um objeto JSON válido (sem markdown):
{{
  "titulo_site": "título SEO máx 65 chars",
  "titulo_social": "título leve para redes sociais",
  "titulo_arte": "máx 6 palavras sem ponto final",
  "subtitulo": "subtítulo do post ou vazio",
  "slug": "slug-sem-acentos-com-hifens",
  "categoria": "nome da categoria",
  "wp_category_id": 12,
  "tags": ["tag1", "tag2"],
  "resumo_telegram": "resumo de 2-3 frases para o editor no Telegram",
  "html": "<p>conteúdo completo...</p>",
  "texto_arte": {{
    "titulo_principal": "máx 6 palavras",
    "linha_apoio": "máx 12 palavras",
    "badge": "categoria para o badge",
    "alerta": ""
  }},
  "creditos_wordpress": {{
    "texto": "crédito de texto adaptado (ver regras abaixo)",
    "fotos": "crédito de fotos ou Divulgação",
    "usar_apenas_no_html_wordpress": true
  }}
}}

REGRAS DE CRÉDITO (campo creditos_wordpress):
- texto: se o release tiver autor/assessoria/MTb → "[nome], com informações de [fonte], reescrito pela equipe do +blog"
  Se não houver → "reescrito pela equipe do +blog"
- fotos: crédito de fotos do release ou "Divulgação"
- Os créditos NÃO devem aparecer no html, legenda, arte ou resumo_telegram — apenas no campo creditos_wordpress"""

    fatos_str = json.dumps(fatos, ensure_ascii=False, indent=2)
    user = f"""Fatos extraídos:
{fatos_str}

Release original:
{release_text[:6000]}"""

    _FALLBACK = {
        "titulo_site": "", "titulo_social": "", "titulo_arte": "", "subtitulo": "",
        "slug": "", "categoria": "Eventos", "wp_category_id": 12, "tags": [],
        "resumo_telegram": "", "html": "",
        "texto_arte": {"titulo_principal": "", "linha_apoio": "", "badge": "", "alerta": ""},
        "creditos_wordpress": {
            "texto": f"reescrito pela equipe do +blog com informações de {sender}" if sender else "reescrito pela equipe do +blog",
            "fotos": fatos.get("creditos_fotos") or "Divulgação",
            "usar_apenas_no_html_wordpress": True,
        },
    }

    try:
        result = llm_call_json(system=system, user=user, model=EDITORIAL_MODEL)
        if isinstance(result, dict) and result.get("titulo_site"):
            # Garante flag de crédito
            if "creditos_wordpress" in result:
                result["creditos_wordpress"]["usar_apenas_no_html_wordpress"] = True
            return result
        return _FALLBACK
    except Exception as e:
        print(f"[editorial] gerar_conteudo falhou: {e}", file=sys.stderr)
        return _FALLBACK
```

- [ ] **Step 2: Commitar**

```bash
git add execution/editorial.py
git commit -m "feat: editorial.py — gerar_conteudo com voz editorial e creditos_wordpress (função 3)"
```

---

## Task 5: `editorial.py` — Função 4: `gerar_legenda`

**Files:**
- Modify: `execution/editorial.py`

- [ ] **Step 1: Adicionar `gerar_legenda`**

```python
def gerar_legenda(fatos: dict, resumo: str) -> dict:
    """
    Gera legenda para Instagram com CTA rotativo.
    Retorna dict com legenda_curta, legenda_contexto, cta_sugerido, hashtags.
    """
    from llm_call import llm_call_json

    _FALLBACK = {
        "legenda_curta": "",
        "legenda_contexto": "",
        "cta_sugerido": "",
        "hashtags": ["#maisblog", "#americana", "#culturaameri"],
    }

    tem_data = bool(fatos.get("data") or fatos.get("horario"))
    tem_programacao = bool(fatos.get("atracoes") and len(fatos["atracoes"]) > 1)

    ctas_disponiveis = [
        "Marca quem iria com você.",
        "Mais detalhes estão no nosso portal.",
        "Quer ver mais rolês assim por aqui? Comenta 'eu quero'.",
        "A gente colocou tudo no +blog pra você se programar melhor.",
        "Já manda pra quem vive procurando o que fazer na região.",
    ]
    if tem_data:
        ctas_disponiveis.insert(0, "Salva pra lembrar desse rolê.")
    if tem_programacao:
        ctas_disponiveis.append("A programação completa está no +blog.")

    system = f"""{_VOZ_EDITORIAL}

Você vai gerar duas versões de legenda para Instagram sobre este conteúdo.

ESTRUTURA DE CADA LEGENDA:
1. Gancho (1 linha) — dado concreto, antes do "ver mais". SEM "Vem aí", "Confira", "Incrível".
2. Corpo — 2 parágrafos curtos com detalhes úteis. Tom de amigo dando dica.
3. CTA — escolha o mais natural entre as opções disponíveis.
4. Hashtags — máx 5, regionais e específicas.

CTAs disponíveis (escolha o mais adequado):
{chr(10).join(f"- {c}" for c in ctas_disponiveis)}

Retorne APENAS um objeto JSON:
{{
  "legenda_curta": "versão direta e objetiva — uso padrão",
  "legenda_contexto": "versão alternativa com mais contexto — para o editor escolher",
  "cta_sugerido": "o CTA escolhido",
  "hashtags": ["#tag1", "#tag2", "#tag3", "#tag4", "#maisblog"]
}}

REGRAS ABSOLUTAS:
- Máx 5 hashtags
- SEM créditos de texto ou fotos nas legendas
- SEM mencionar a assessoria ou fonte da notícia"""

    fatos_str = json.dumps(fatos, ensure_ascii=False, indent=2)
    user = f"""Fatos do post:
{fatos_str}

Resumo da matéria:
{resumo[:500]}"""

    try:
        result = llm_call_json(system=system, user=user, model=EDITORIAL_MODEL)
        if isinstance(result, dict) and result.get("legenda_curta"):
            return result
        return _FALLBACK
    except Exception as e:
        print(f"[editorial] gerar_legenda falhou: {e}", file=sys.stderr)
        return _FALLBACK
```

- [ ] **Step 2: Commitar**

```bash
git add execution/editorial.py
git commit -m "feat: editorial.py — gerar_legenda com CTAs rotativos (função 4)"
```

---

## Task 6: `editorial.py` — Função 5: `validar_fatos`

**Files:**
- Modify: `execution/editorial.py`

- [ ] **Step 1: Adicionar `validar_fatos`**

```python
def validar_fatos(release_text: str, fatos: dict, post: dict) -> dict:
    """
    Valida se o conteúdo gerado é fiel ao release original.
    Fallback aprovador: não bloqueia o pipeline se o validador falhar.
    """
    from llm_call import llm_call_json

    _FALLBACK_APROVADO = {
        "aprovado": True,
        "risco_alucinacao": "baixo",
        "problemas": [],
        "observacao_editorial": "",
    }

    system = """Você é um verificador de fatos para um portal de notícias. Compare o conteúdo gerado com o release original e os fatos extraídos.

Verifique se o conteúdo inventou ou distorceu: datas, horários, cidade, local, valor, gratuidade, atrações, nomes de pessoas/projetos/instituições, links, inscrição, público-alvo.

Também verifique chamadas exageradas ou afirmações não suportadas pelo release.

Retorne APENAS um objeto JSON:
{
  "aprovado": true/false,
  "risco_alucinacao": "baixo|medio|alto",
  "problemas": [
    {
      "trecho": "trecho problemático do conteúdo gerado",
      "problema": "descrição do problema",
      "correcao_sugerida": "como corrigir"
    }
  ],
  "observacao_editorial": "observação geral opcional"
}

Se não houver problemas, retorne aprovado=true, risco=baixo, problemas=[]."""

    html_sem_tags = post.get("html", "")[:2000]
    user = f"""Release original (fonte da verdade):
{release_text[:3000]}

Fatos extraídos:
{json.dumps(fatos, ensure_ascii=False)}

Conteúdo gerado para verificar:
Título: {post.get("titulo_site", "")}
Resumo Telegram: {post.get("resumo_telegram", "")}
HTML (parcial): {html_sem_tags}
Legenda IG: {post.get("legenda_curta", "")}"""

    try:
        result = llm_call_json(system=system, user=user, model=EDITORIAL_MODEL)
        if isinstance(result, dict) and "aprovado" in result:
            return result
        return _FALLBACK_APROVADO
    except Exception as e:
        print(f"[editorial] validar_fatos falhou (aviso, pipeline continua): {e}", file=sys.stderr)
        return _FALLBACK_APROVADO
```

- [ ] **Step 2: Commitar**

```bash
git add execution/editorial.py
git commit -m "feat: editorial.py — validar_fatos anti-alucinação (função 5)"
```

---

## Task 7: `editorial.py` — Função 6: `resumo_telegram`

**Files:**
- Modify: `execution/editorial.py`

- [ ] **Step 1: Adicionar `resumo_telegram` (sem LLM)**

```python
def resumo_telegram(post: dict, validacao: dict, avaliacao: dict) -> dict:
    """
    Monta o resumo para o card do Telegram a partir de dados já gerados.
    Zero LLM calls — custo zero.
    """
    risco = validacao.get("risco_alucinacao", "baixo")
    alertas = []
    if risco in ("medio", "alto"):
        for p in validacao.get("problemas", []):
            if p.get("trecho"):
                alertas.append(f"{p['trecho'][:60]}: {p.get('problema', '')[:80]}")

    return {
        "titulo_card": post.get("titulo_site", ""),
        "cidade": avaliacao.get("cidade", ""),
        "categoria": post.get("categoria", ""),
        "por_que_importa": post.get("resumo_telegram", ""),
        "potencial_site": str(avaliacao.get("potencial_google", 0)),
        "potencial_instagram": str(avaliacao.get("potencial_instagram", 0)),
        "urgencia": str(avaliacao.get("urgencia", 0)),
        "acao_recomendada": avaliacao.get("observacao_para_editor", ""),
        "alertas": alertas,
    }
```

- [ ] **Step 2: Commitar**

```bash
git add execution/editorial.py
git commit -m "feat: editorial.py — resumo_telegram sem LLM (função 6)"
```

---

## Task 8: Adicionar `_query_from_fatos` em `editorial.py`

**Files:**
- Modify: `execution/editorial.py`

- [ ] **Step 1: Adicionar função auxiliar para query de imagem**

```python
def query_from_fatos(fatos: dict, titulo: str) -> str:
    """
    Gera query de busca de imagem a partir dos fatos extraídos.
    Elimina a necessidade de uma LLM call adicional.
    """
    partes = []
    if fatos.get("atracoes"):
        partes.append(fatos["atracoes"][0])
    if fatos.get("categoria_editorial"):
        partes.append(fatos["categoria_editorial"])
    return " ".join(partes) or titulo[:60]
```

- [ ] **Step 2: Commitar**

```bash
git add execution/editorial.py
git commit -m "feat: editorial.py — query_from_fatos elimina LLM call de imagem"
```

---

## Task 9: Atualizar `sheets_write.py` — coluna `legenda_longa`

**Files:**
- Modify: `execution/sheets_write.py`

O header atual de Legendas IG é:
```python
"Legendas IG": [
    "id_post", "titulo", "legenda", "hashtags",
    "status", "data_postagem", "path_imagem",
],
```

- [ ] **Step 1: Adicionar `legenda_longa` ao header da aba Legendas IG**

Em `sheets_write.py`, localizar a linha com `"Legendas IG"` no dict `HEADERS` e alterar:

```python
# ANTES
"Legendas IG": [
    "id_post", "titulo", "legenda", "hashtags",
    "status", "data_postagem", "path_imagem",
],

# DEPOIS
"Legendas IG": [
    "id_post", "titulo", "legenda", "hashtags",
    "status", "data_postagem", "path_imagem", "legenda_longa",
],
```

- [ ] **Step 2: Atualizar `cmd_legenda_ig` para gravar `legenda_longa`**

```python
# ANTES
def cmd_legenda_ig(data: dict) -> dict:
    row = [
        str(data.get("id_post", "")),
        data.get("titulo", ""),
        data.get("legenda", ""),
        data.get("hashtags", ""),
        data.get("status", "Pronta"),
        data.get("data_postagem", ""),
        data.get("path_imagem", ""),
    ]
    return _append_row("Legendas IG", row)

# DEPOIS
def cmd_legenda_ig(data: dict) -> dict:
    row = [
        str(data.get("id_post", "")),
        data.get("titulo", ""),
        data.get("legenda", ""),
        data.get("hashtags", ""),
        data.get("status", "Pronta"),
        data.get("data_postagem", ""),
        data.get("path_imagem", ""),
        data.get("legenda_longa", ""),
    ]
    return _append_row("Legendas IG", row)
```

- [ ] **Step 3: Verificar que nenhuma outra função acessa Legendas IG por índice numérico de coluna**

Grep para confirmar:
```bash
grep -n "Legendas IG" execution/sheets_write.py execution/sheets_read.py
```
O `update-status` usa `headers.index("status")` — funciona corretamente porque busca por nome.

- [ ] **Step 4: Commitar**

```bash
git add execution/sheets_write.py
git commit -m "feat: sheets_write — coluna legenda_longa na aba Legendas IG"
```

> **NOTA para o operador:** após commitar, acessar a planilha "Operação +blog" manualmente e adicionar o cabeçalho `legenda_longa` na coluna H da aba Legendas IG. O `cmd_setup` não é re-rodado em produção.

---

## Task 10: Atualizar `instagram_image.py` — args `--art-title` e `--art-subtitle`

**Files:**
- Modify: `execution/instagram_image.py`

- [ ] **Step 1: Adicionar args opcionais ao `main()` e passá-los a `generate_ig_image`**

Em `instagram_image.py`, no `main()`, adicionar dois args após `--output-dir`:

```python
# Adicionar após a linha: parser.add_argument("--output-dir", default=".tmp")
parser.add_argument("--art-title", default="", help="Título principal da arte (opcional, substitui --title)")
parser.add_argument("--art-subtitle", default="", help="Linha de apoio da arte (opcional)")
```

Atualizar a chamada a `generate_ig_image`:

```python
# ANTES
result = generate_ig_image(args.cover, args.category, args.title, args.slug, args.output_dir)

# DEPOIS
art_title = args.art_title if args.art_title else args.title
result = generate_ig_image(args.cover, args.category, art_title, args.slug, args.output_dir)
```

- [ ] **Step 2: Verificar que `--art-subtitle` é aceito (mesmo que não usado no layout ainda)**

O `--art-subtitle` é aceito via argparse mas não altera o layout nesta fase (fica disponível para fase 2). Confirmar que o argparse não quebra se passado.

- [ ] **Step 3: Commitar**

```bash
git add execution/instagram_image.py
git commit -m "feat: instagram_image — args opcionais --art-title e --art-subtitle"
```

---

## Task 11: Atualizar `telegram_notify.py` — `--card-meta` e novo formato do card

**Files:**
- Modify: `execution/telegram_notify.py`

- [ ] **Step 1: Adicionar `--card-meta` ao argparser de `send-release`**

No `main()` de `telegram_notify.py`, adicionar após `--ig-caption`:

```python
p_sr.add_argument("--card-meta", default="", help="JSON string com campos de resumo_telegram")
```

- [ ] **Step 2: Atualizar a assinatura de `cmd_send_release` para aceitar `card_meta`**

```python
# ANTES
def cmd_send_release(post_id: int, title: str, summary: str, edit_url: str,
                     cover: str, sheets_row_id: str,
                     ig_image_path: str = "", ig_caption: str = "") -> dict:

# DEPOIS
def cmd_send_release(post_id: int, title: str, summary: str, edit_url: str,
                     cover: str, sheets_row_id: str,
                     ig_image_path: str = "", ig_caption: str = "",
                     card_meta: dict | None = None) -> dict:
```

- [ ] **Step 3: Substituir o texto do card quando `card_meta` estiver presente**

Localizar onde `caption` é montado em `cmd_send_release` e substituir:

```python
# ANTES
caption = (
    f"📰 *{_escape(title)}*\n\n"
    f"{_escape(summary)}\n\n"
    f"[Editar rascunho]({edit_url})"
)

# DEPOIS
if card_meta:
    cidade = card_meta.get("cidade", "")
    categoria = card_meta.get("categoria", "")
    por_que = card_meta.get("por_que_importa", summary)
    site_score = card_meta.get("potencial_site", "")
    ig_score = card_meta.get("potencial_instagram", "")
    urgencia = card_meta.get("urgencia", "")
    acao = card_meta.get("acao_recomendada", "")
    alertas = card_meta.get("alertas", [])

    loc_cat = f"📍 {_escape(cidade)} · {_escape(categoria)}" if cidade or categoria else ""
    scores = f"📊 Site {site_score}/10 · Instagram {ig_score}/10" if site_score or ig_score else ""
    urg_line = f"⏰ Urgência: {urgencia}/10" if urgencia else ""
    acao_line = f"💡 {_escape(acao)}" if acao else ""
    alerta_line = (
        f"⚠️ Revisar: {_escape('; '.join(alertas[:2]))}"
        if alertas else ""
    )

    partes = [
        f"📰 *{_escape(title)}*",
        loc_cat,
        "",
        _escape(por_que[:200]),
        "",
        scores,
        urg_line,
        acao_line,
        alerta_line,
        "",
        f"[Editar rascunho]({edit_url})",
    ]
    caption = "\n".join(p for p in partes if p is not None)
    # Remove linhas consecutivas em branco
    import re as _re
    caption = _re.sub(r"\n{3,}", "\n\n", caption).strip()
else:
    caption = (
        f"📰 *{_escape(title)}*\n\n"
        f"{_escape(summary)}\n\n"
        f"[Editar rascunho]({edit_url})"
    )
```

- [ ] **Step 4: Atualizar a chamada no `main()` para passar `card_meta`**

```python
# ANTES
result = cmd_send_release(
    args.post_id, args.title, args.summary,
    args.edit_url, args.cover, args.sheets_row_id,
    ig_image_path=args.ig_image,
    ig_caption=args.ig_caption,
)

# DEPOIS
card_meta_parsed = json.loads(args.card_meta) if args.card_meta else None
result = cmd_send_release(
    args.post_id, args.title, args.summary,
    args.edit_url, args.cover, args.sheets_row_id,
    ig_image_path=args.ig_image,
    ig_caption=args.ig_caption,
    card_meta=card_meta_parsed,
)
```

- [ ] **Step 5: Commitar**

```bash
git add execution/telegram_notify.py
git commit -m "feat: telegram_notify — card enriquecido com scores via --card-meta"
```

---

## Task 12: Atualizar `run_releases.py` — conectar tudo

**Files:**
- Modify: `execution/run_releases.py`

Esta é a tarefa de integração. O fluxo completo de `processar_email()` será reescrito para usar o módulo `editorial`.

- [ ] **Step 1: Remover as 3 funções LLM internas e `_gerar_query_imagem`**

Apagar completamente as funções:
- `_llm_relevancia()` (linhas 110–141)
- `_llm_reescrever()` (linhas 144–275)
- `_llm_legenda_ig()` (linhas 278–326)
- `_gerar_query_imagem()` (linhas 404–435)

- [ ] **Step 2: Atualizar `_pipeline_imagem` para usar `query_from_fatos`**

Localizar a linha onde `_gerar_query_imagem` é chamada em `_pipeline_imagem` e substituir:

```python
# ANTES (dentro de _pipeline_imagem, após o bloco de fotos do email)
img_query = _gerar_query_imagem(titulo)

# DEPOIS
from editorial import query_from_fatos
img_query = query_from_fatos(fatos, titulo)
```

A assinatura de `_pipeline_imagem` precisa aceitar `fatos`:

```python
# ANTES
def _pipeline_imagem(email: dict, slug: str, titulo: str = "") -> tuple[str, str]:

# DEPOIS
def _pipeline_imagem(email: dict, slug: str, titulo: str = "", fatos: dict | None = None) -> tuple[str, str]:
```

E no início do corpo da função, antes do bloco de fotos:

```python
if fatos is None:
    fatos = {}
```

- [ ] **Step 3: Reescrever `processar_email()` com o novo fluxo editorial**

Substituir todo o corpo de `processar_email()` mantendo a mesma assinatura. O novo fluxo:

```python
def processar_email(email: dict, dry_run: bool = False, processed_subjects: set | None = None) -> dict:
    """Processa um email pelo pipeline completo. Retorna dict com resultado."""
    from editorial import (
        extrair_fatos, avaliar_relevancia, gerar_conteudo,
        gerar_legenda, validar_fatos, resumo_telegram,
    )

    email_id = email.get("id", "?")
    subject = email.get("subject", "")
    sender = email.get("sender", "")
    date = email.get("date", "")
    body_text = email.get("body_text", "") or email.get("body_html", "")[:8000]

    # Deduplicação 1: arquivo local
    if not dry_run and email_id in _load_processed():
        print(f"\n[run_releases] → Já processado (arquivo), pulando: {subject[:60]}", file=sys.stderr)
        return {"email_id": email_id, "relevante": False, "motivo": "Já processado anteriormente"}

    # Deduplicação 2: Sheets (persistente)
    if not dry_run and processed_subjects is not None:
        key = (subject.strip().lower(), sender.strip().lower())
        if key in processed_subjects:
            print(f"\n[run_releases] → Já na planilha, pulando: {subject[:60]}", file=sys.stderr)
            return {"email_id": email_id, "relevante": False, "motivo": "Já registrado na planilha"}

    print(f"\n[run_releases] → Processando: {subject[:60]}", file=sys.stderr)

    # 1. Extrai fatos
    print(f"[run_releases]   1/6 Extraindo fatos...", file=sys.stderr)
    fatos = extrair_fatos(body_text)

    # 2. Avalia relevância
    print(f"[run_releases]   2/6 Avaliando relevância...", file=sys.stderr)
    avaliacao = avaliar_relevancia(body_text, fatos)
    relevante = avaliacao.get("relevante", False)

    if not relevante:
        motivo = avaliacao.get("motivo_aprovacao_ou_descarte", "Não relevante")
        print(f"[run_releases]   Não relevante: {motivo}", file=sys.stderr)
        if not dry_run:
            _run_json([
                str(SCRIPT_DIR / "sheets_write.py"), "log-release",
                "--data", json.dumps({
                    "sender": sender, "subject": subject, "date": date,
                    "relevante": False, "status": "Descartado",
                    "motivo_descarte": motivo,
                }, ensure_ascii=False),
            ])
        return {"email_id": email_id, "relevante": False, "motivo": motivo}

    # 3. Gera conteúdo editorial
    print(f"[run_releases]   3/6 Gerando conteúdo...", file=sys.stderr)
    post = gerar_conteudo(body_text, fatos, avaliacao, sender=sender)

    titulo = post.get("titulo_site") or subject[:65]
    slug = post.get("slug") or "post-sem-slug"
    html = post.get("html", "")
    wp_category_id = post.get("wp_category_id", 12)
    if wp_category_id not in VALID_CATEGORY_IDS:
        print(f"[run_releases]   Categoria inválida ({wp_category_id}), usando Eventos (12).", file=sys.stderr)
        wp_category_id = 12
    tags = post.get("tags", [])
    creditos = post.get("creditos_wordpress", {})

    print(f"[run_releases]   Título: {titulo}", file=sys.stderr)

    if dry_run:
        return {"email_id": email_id, "relevante": True, "titulo": titulo, "slug": slug, "dry_run": True}

    # 4. Pipeline de imagem (usa fatos para query — sem LLM extra)
    cover_path, foto_credit_gerada = _pipeline_imagem(email, slug, titulo, fatos=fatos)
    if not cover_path:
        print(f"[run_releases]   Aviso: sem imagem de capa.", file=sys.stderr)

    # Crédito de foto: release > gerada > Divulgação
    foto_credit = creditos.get("fotos") or foto_credit_gerada or "Divulgação"

    # 5. Arte Instagram
    ig_path = ""
    ig_url = ""
    if cover_path and Path(cover_path).exists():
        category_name = CATEGORY_NAMES.get(wp_category_id, "Eventos")
        art_title = post.get("texto_arte", {}).get("titulo_principal", "")
        art_subtitle = post.get("texto_arte", {}).get("linha_apoio", "")
        ig_args = [
            str(SCRIPT_DIR / "instagram_image.py"),
            "--cover", cover_path,
            "--slug", slug,
            "--title", titulo,
            "--category", category_name,
            "--output-dir", OUTPUT_DIR,
        ]
        if art_title:
            ig_args += ["--art-title", art_title]
        if art_subtitle:
            ig_args += ["--art-subtitle", art_subtitle]
        ig_result = _run_json(ig_args)
        if ig_result:
            ig_path = ig_result.get("path", "")

    # Upload da arte IG para WP
    if ig_path and Path(ig_path).exists():
        upload_result = _run_json([
            str(SCRIPT_DIR / "wp_publish.py"), "upload-image",
            "--image-path", ig_path,
            "--title", f"{titulo} — Instagram",
        ])
        if upload_result:
            ig_url = upload_result.get("url", "")

    # 6. Legenda Instagram (sem créditos)
    print(f"[run_releases]   4/6 Gerando legenda IG...", file=sys.stderr)
    legendas = gerar_legenda(fatos, post.get("resumo_telegram", ""))
    legenda_curta = legendas.get("legenda_curta", "")
    legenda_longa = legendas.get("legenda_contexto", "")
    hashtags = legendas.get("hashtags", [])

    # 7. Validação factual
    print(f"[run_releases]   5/6 Validando fatos...", file=sys.stderr)
    # Passa post enriquecido com legenda para validação
    post_para_validar = {**post, "legenda_curta": legenda_curta}
    validacao = validar_fatos(body_text, fatos, post_para_validar)
    risco = validacao.get("risco_alucinacao", "baixo")
    if risco != "baixo":
        print(f"[run_releases]   ⚠️ Risco de alucinação: {risco}", file=sys.stderr)

    # 8. Resumo para Telegram
    print(f"[run_releases]   6/6 Montando resumo Telegram...", file=sys.stderr)
    card_meta = resumo_telegram(post, validacao, avaliacao)

    # 9. HTML com bloco de créditos ao final
    credito_texto = creditos.get("texto", f"reescrito pela equipe do +blog com informações de {sender}").strip()
    creditos_html = f'<p><em>Texto: {credito_texto}. Fotos: {foto_credit}</em></p>'
    html_com_creditos = html + "\n" + creditos_html

    # 10. Publica rascunho no WordPress
    wp_args = [
        str(SCRIPT_DIR / "wp_publish.py"), "create",
        "--title", titulo,
        "--html", html_com_creditos,
        "--category-id", str(wp_category_id),
    ]
    if cover_path:
        wp_args += ["--image-path", cover_path]
    if tags:
        wp_args += ["--tags", ",".join(tags)]

    wp_result = _run_json(wp_args)
    if not wp_result:
        print(f"[run_releases]   Erro ao criar rascunho no WP.", file=sys.stderr)
        return {"email_id": email_id, "relevante": True, "titulo": titulo, "error": "wp_publish falhou"}

    _mark_processed(email_id)
    post_id = wp_result.get("post_id")
    edit_url = wp_result.get("edit_url", "")

    # 11. Registra no Sheets
    sheets_log = _run_json([
        str(SCRIPT_DIR / "sheets_write.py"), "log-release",
        "--data", json.dumps({
            "sender": sender, "subject": subject, "date": date,
            "relevante": True, "status": "Aguardando aprovação",
            "link_post": edit_url,
        }, ensure_ascii=False),
    ])
    sheets_row_id = sheets_log.get("row_id", "0") if sheets_log else "0"

    if ig_url:
        _run_json([
            str(SCRIPT_DIR / "sheets_write.py"), "legenda-ig",
            "--data", json.dumps({
                "id_post": str(post_id),
                "titulo": titulo,
                "legenda": legenda_curta,
                "hashtags": " ".join(hashtags),
                "status": "Pronta",
                "path_imagem": ig_url,
                "legenda_longa": legenda_longa,
            }, ensure_ascii=False),
        ])

    # 12. Notifica Telegram com card enriquecido
    notify_args = [
        str(SCRIPT_DIR / "telegram_notify.py"), "send-release",
        "--post-id", str(post_id),
        "--title", titulo,
        "--summary", post.get("resumo_telegram", html[:300].replace("<", "").replace(">", "")[:200]),
        "--edit-url", edit_url,
        "--cover", cover_path or "",
        "--sheets-row-id", sheets_row_id,
        "--card-meta", json.dumps(card_meta, ensure_ascii=False),
    ]
    if ig_path:
        notify_args += ["--ig-image", ig_path, "--ig-caption", legenda_curta]
    _run(notify_args)

    print(f"[run_releases]   ✅ Rascunho #{post_id} criado. Card enviado ao Telegram.", file=sys.stderr)

    return {
        "email_id": email_id,
        "relevante": True,
        "titulo": titulo,
        "post_id": post_id,
        "sheets_row_id": sheets_row_id,
        "risco_alucinacao": risco,
    }
```

- [ ] **Step 4: Verificar que `llm_call` não é mais importado em nível de módulo em `run_releases.py`**

Confirmar que não há mais referência a `_llm_relevancia`, `_llm_reescrever`, `_llm_legenda_ig`, `_gerar_query_imagem` no arquivo.

```bash
grep -n "_llm_\|_gerar_query" execution/run_releases.py
```

Resultado esperado: sem matches.

- [ ] **Step 5: Commitar**

```bash
git add execution/run_releases.py
git commit -m "feat: run_releases — integra módulo editorial completo (6 funções)"
```

---

## Task 13: Smoke test manual com `--dry-run`

**Files:**
- Nenhum (apenas execução)

- [ ] **Step 1: Verificar que o módulo `editorial.py` importa sem erros**

```bash
python -c "from execution.editorial import extrair_fatos, avaliar_relevancia, gerar_conteudo, gerar_legenda, validar_fatos, resumo_telegram, query_from_fatos; print('OK')"
```

Resultado esperado: `OK`

- [ ] **Step 2: Rodar o pipeline em dry-run**

```bash
python execution/run_releases.py --dry-run --max 3
```

Resultado esperado:
- Conecta ao IMAP
- Para cada email: imprime log `1/6 Extraindo fatos...` até `6/6 Montando resumo...`
- Retorna JSON com `dry_run: true`
- Nenhum post criado no WP, nenhuma mensagem no Telegram

- [ ] **Step 3: Testar `telegram_notify.py` com `--card-meta`**

```bash
python execution/telegram_notify.py send-text --message "Teste editorial upgrade OK"
```

Resultado esperado: mensagem recebida no Telegram.

- [ ] **Step 4: Commit final de ajustes se necessário**

```bash
git add -A
git commit -m "fix: ajustes pós smoke-test do upgrade editorial"
```

---

## Task 14: Deploy para produção

**Files:**
- Nenhum (deploy via Coolify)

- [ ] **Step 1: Push para o repositório**

```bash
git push origin main
```

- [ ] **Step 2: Acionar redeploy via API do Coolify**

```bash
curl -X POST \
  -H "Authorization: Bearer 4|KhjNZW4NJw39fm8eBKAeK21WMFGTnx4w92JsTunde8590ac2" \
  "https://serv2.criatoin.com.br/api/v1/deploy?uuid=ksko44gg48k0wsg04sosscsc&force=true"
```

Resultado esperado: `{"message":"Deployment request queued."}` ou similar.

- [ ] **Step 3: Adicionar coluna `legenda_longa` na planilha manualmente**

Acessar a planilha "Operação +blog" → aba "Legendas IG" → adicionar cabeçalho `legenda_longa` na coluna H (após `path_imagem`).

- [ ] **Step 4: Aguardar o próximo ciclo do cron e confirmar card no Telegram**

O cron roda todo hora em dias úteis (8h–18h). O próximo card recebido no Telegram deve ter o novo formato:
```
📰 *Título do post*
📍 Americana · Música

Resumo do por que importa...

📊 Site 8/10 · Instagram 7/10
⏰ Urgência: 6/10
💡 Observação para o editor
```

---

## Self-Review

**Cobertura da spec:**
- ✅ `EDITORIAL_MODEL` env var — Task 1
- ✅ `_VOZ_EDITORIAL` bloco fixo — Task 1
- ✅ `extrair_fatos` com schema completo — Task 2
- ✅ `avaliar_relevancia` com scores — Task 3
- ✅ `gerar_conteudo` com `creditos_wordpress` exclusivo para WP — Task 4
- ✅ `gerar_legenda` com CTAs rotativos, sem créditos — Task 5
- ✅ `validar_fatos` com fallback aprovador — Task 6
- ✅ `resumo_telegram` sem LLM — Task 7
- ✅ `query_from_fatos` eliminando LLM call — Task 8
- ✅ `legenda_longa` no Sheets — Task 9
- ✅ `--art-title`/`--art-subtitle` no instagram_image — Task 10
- ✅ `--card-meta` e novo card no telegram_notify — Task 11
- ✅ `processar_email()` integrado com fluxo de 12 passos — Task 12
- ✅ Créditos exclusivos no HTML do WP (não vazam para arte/legenda/Telegram) — Task 12 step 3
- ✅ Smoke test e deploy — Tasks 13–14

**Tipos consistentes:**
- `extrair_fatos` retorna `dict` — consumido por `avaliar_relevancia`, `gerar_conteudo`, `gerar_legenda`, `validar_fatos`
- `gerar_conteudo` retorna `dict` com chave `creditos_wordpress` (não `creditos`) — Task 12 usa `post.get("creditos_wordpress", {})`
- `resumo_telegram` retorna `dict` — serializado como JSON em `--card-meta`
- `query_from_fatos` aceita `(fatos: dict, titulo: str)` — chamada em `_pipeline_imagem` com `fatos=fatos`
