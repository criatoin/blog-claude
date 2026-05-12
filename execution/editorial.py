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
  "gratuito": true/false/null,
  "inscricao_necessaria": true/false/null,
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
            return {**_FATOS_VAZIOS, **result}
        return _FATOS_VAZIOS
    except Exception as e:
        print(f"[editorial] extrair_fatos falhou: {e}", file=sys.stderr)
        return _FATOS_VAZIOS


def avaliar_relevancia(release_text: str, fatos: dict) -> dict:
    """
    Avalia relevância editorial com scores numéricos.
    Fallback conservador: relevante=False.
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


def gerar_conteudo(release_text: str, fatos: dict, avaliacao: dict, sender: str = "") -> dict:
    """
    Gera o conteúdo editorial completo do post.
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
    "texto": "crédito de texto adaptado",
    "fotos": "crédito de fotos ou Divulgação",
    "usar_apenas_no_html_wordpress": true
  }}
}}

REGRAS DE CRÉDITO (campo creditos_wordpress):
- texto: se o release tiver autor/assessoria/MTb → "[nome], com informações de [fonte], reescrito pela equipe do +blog"
  Se não houver → "reescrito pela equipe do +blog"
- fotos: crédito de fotos do release ou "Divulgação"
- Os créditos NÃO devem aparecer no html, legenda, arte ou resumo_telegram"""

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

    fatos_str = json.dumps(fatos, ensure_ascii=False, indent=2)
    user = f"""Fatos extraídos:
{fatos_str}

Release original:
{release_text[:6000]}"""

    try:
        result = llm_call_json(system=system, user=user, model=EDITORIAL_MODEL)
        if isinstance(result, dict) and result.get("titulo_site"):
            if "creditos_wordpress" in result:
                result["creditos_wordpress"]["usar_apenas_no_html_wordpress"] = True
            return result
        return _FALLBACK
    except Exception as e:
        print(f"[editorial] gerar_conteudo falhou: {e}", file=sys.stderr)
        return _FALLBACK


def gerar_legenda(fatos: dict, resumo: str) -> dict:
    """
    Gera legenda para Instagram com CTA rotativo.
    Sem créditos — créditos são exclusivos do HTML WordPress.
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


def resumo_telegram(post: dict, validacao: dict, avaliacao: dict) -> dict:
    """
    Monta o resumo para o card do Telegram a partir de dados já gerados.
    Zero LLM calls.
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
