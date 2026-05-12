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
  "subtitulo": "subtítulo do post ou vazio",
  "slug": "slug-sem-acentos-com-hifens",
  "categoria": "nome da categoria",
  "wp_category_id": 12,
  "tags": ["tag1", "tag2"],
  "resumo_telegram": "resumo de 2-3 frases para o editor no Telegram",
  "html": "<p>conteúdo completo...</p>",
  "texto_arte": {{
    "template": "ameriafro_v3",
    "badge": "1 ou 2 palavras em maiúsculas — ex: CULTURA, LITERATURA, MÚSICA",
    "titulo_principal": "até 6 palavras — manchete visual, sem ponto final, sem hashtag",
    "linha_apoio": "até 12 palavras — contextualiza sem virar parágrafo, sem hashtag",
    "alerta": "vazio se OK, ou aviso se faltou info para chamada segura"
  }},
  "creditos_wordpress": {{
    "texto": "crédito de texto adaptado",
    "fotos": "crédito de fotos ou Divulgação",
    "usar_apenas_no_html_wordpress": true
  }}
}}

════════════════════════════════
REGRAS PARA texto_arte
════════════════════════════════
- badge: 1 ou 2 palavras em maiúsculas (ex: "LITERATURA", "MÚSICA", "CULTURA")
- titulo_principal: máx 6 palavras, SEM ponto final, SEM hashtags (#)
- titulo_principal NÃO pode ser igual ao titulo_site
- titulo_principal NÃO pode conter: "imperdível", "confira", "não perca", "vem aí", "promete", "programação especial", "acontece em"
- linha_apoio: máx 12 palavras, sem ponto final, sem hashtag, não repetir o título
- NUNCA usar hashtags (#) em nenhum campo de texto_arte
- só usar "gratuito" ou "grátis" se gratuito=true nos fatos extraídos
- só mencionar cidade, data ou local se estiverem nos fatos extraídos
- titulo_principal deve parecer manchete de post social, não frase de release:
    CERTO: "Histórias que encantam", "Cultura preta na Estação", "Americana recebe Sarau Ameriafro"
    ERRADO: "Evento acontece em Santa Bárbara", "Projeto leva magia da leitura para crianças"

════════════════════════════════
REGRAS DE CRÉDITO (campo creditos_wordpress)
════════════════════════════════
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


def gerar_legenda(fatos: dict, resumo: str, arte_instagram: dict | None = None) -> dict:
    """
    Gera legenda para Instagram.
    arte_instagram: dict com titulo_principal/linha_apoio/badge — evita repetir texto da arte.
    Sem créditos — créditos são exclusivos do HTML WordPress.
    """
    from llm_call import llm_call_json

    _FALLBACK = {
        "legenda_curta": "Tem programação cultural chegando por aqui.\n\nA gente reuniu no +blog as informações confirmadas para você entender melhor o que vai rolar e se programar.\n\nVale salvar e mandar para quem curte esse tipo de rolê.",
        "legenda_contexto": "",
        "cta_sugerido": "",
    }

    arte = arte_instagram or {}
    arte_str = ""
    if arte.get("titulo_principal"):
        arte_str = f"badge: {arte.get('badge', '')}\ntitulo: {arte.get('titulo_principal', '')}\nlinha_apoio: {arte.get('linha_apoio', '')}"

    fatos_str = json.dumps(fatos, ensure_ascii=False, indent=2)

    system = f"""{_VOZ_EDITORIAL}

Você é social media do +blog. Crie duas versões de legenda para Instagram.

A legenda precisa soar como Instagram de verdade — humana, leve, regional e natural.
NÃO deve parecer release. NÃO deve parecer resumo frio. NÃO deve ser institucional.
NÃO usar hashtags em hipótese alguma.

ESTRUTURA:
1. Abertura informativa e natural (1-2 frases — dado concreto, não "Vem aí" nem "Confira")
2. Desenvolvimento com o que vai acontecer (detalhes confirmados)
3. Frase que convide a salvar, marcar alguém, viver ou acompanhar
4. CTA final orgânico e variado conforme o conteúdo

ESCOLHA DE CTA conforme o conteúdo:
- evento com data confirmada → sugerir salvar na agenda
- evento cultural → sugerir chamar ou marcar alguém
- programação com mais detalhes → sugerir acessar o +blog
- conteúdo inspirador → sugerir mandar pra quem precisa ver

USE COMO REFERÊNCIA DE ESTILO (não copie, inspire-se no tom e ritmo):
"O 1º Sarau Ameriafro chega na Estação Cultura no dia 16 de maio, com programação gratuita das 14h às 21h

Vai ter poesia, hip hop, capoeira, dança, grafite, maracatu, música, artes visuais, batalha de rima e gente da região ocupando a cidade com cultura afro-brasileira

É o tipo de evento pra salvar na agenda, chamar alguém e viver de perto

Quem você levaria nesse rolê? Marca aqui

No +blog tem a programação completa com horários e atrações pra você se organizar antes de ir"

REGRAS ABSOLUTAS:
- NUNCA usar hashtags (#) — nem uma sequer
- não inventar data, horário, local, cidade, valor ou gratuidade
- não repetir mecanicamente o texto da arte
- não usar "imperdível"
- não usar linguagem institucional
- sem créditos de texto ou fotos
- sem mencionar assessoria ou fonte
- frases fluidas, com ritmo, tom próximo e regional

Retorne APENAS um objeto JSON válido:
{{
  "legenda_curta": "versão direta — gancho + desenvolvimento + convite + CTA. SEM hashtags.",
  "legenda_contexto": "versão alternativa com mais contexto — para o editor escolher. SEM hashtags.",
  "cta_sugerido": "o CTA escolhido"
}}"""

    user_parts = [f"Fatos confirmados:\n{fatos_str}", f"Resumo da matéria:\n{resumo[:500]}"]
    if arte_str:
        user_parts.append(f"Texto da arte (não repetir mecanicamente):\n{arte_str}")
    user = "\n\n".join(user_parts)

    try:
        result = llm_call_json(system=system, user=user, model=EDITORIAL_MODEL)
        if isinstance(result, dict) and result.get("legenda_curta"):
            # Remove hashtags residuais linha a linha
            for campo in ("legenda_curta", "legenda_contexto"):
                if campo in result:
                    linhas = [l for l in result[campo].splitlines() if not l.strip().startswith("#")]
                    result[campo] = "\n".join(linhas)
            result.pop("hashtags", None)  # remove se LLM devolver mesmo proibido
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
        for p in (validacao.get("problemas") or []):
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
        primeiro = fatos["atracoes"][0]
        if isinstance(primeiro, str):
            partes.append(primeiro)
    if fatos.get("categoria_editorial"):
        partes.append(fatos["categoria_editorial"])
    return " ".join(partes) or titulo[:60]


# ─── Validação de texto da arte ──────────────────────────────────────────────

_PALAVRAS_PROIBIDAS_ARTE = [
    "imperdível", "confira", "não perca", "vem aí",
    "programação especial", "promete", "acontece em",
]


def _fallback_titulo_arte(fatos: dict) -> str:
    projeto = fatos.get("projeto", "").strip()
    categoria = fatos.get("categoria_editorial", "Evento").strip()
    cidade = fatos.get("cidade", "").strip()
    if projeto and len(projeto.split()) <= 5:
        return projeto
    if cidade:
        return f"{categoria} em {cidade}"
    return categoria


def _fallback_linha_arte(fatos: dict) -> str:
    partes = []
    if fatos.get("cidade"):
        partes.append(fatos["cidade"])
    if fatos.get("data"):
        partes.append(fatos["data"])
    elif fatos.get("local"):
        partes.append(fatos["local"])
    return ", ".join(partes) if partes else ""


def validar_arte(arte: dict, fatos: dict, release_titulo: str = "") -> tuple[dict, list[str]]:
    """
    Valida e corrige o texto da arte antes de renderizar.
    Nunca bloqueia o pipeline — aplica fallback determinístico se inválido.
    Retorna (arte_corrigida, lista_de_alertas).
    """
    alertas: list[str] = []
    titulo = arte.get("titulo_principal", "").strip()
    linha  = arte.get("linha_apoio", "").strip()
    badge  = arte.get("badge", "").strip()

    # 1. Título existe
    if not titulo:
        alertas.append("titulo_principal vazio — aplicando fallback")
        titulo = _fallback_titulo_arte(fatos)

    # 2. Máx 6 palavras
    palavras = titulo.split()
    if len(palavras) > 6:
        alertas.append(f"titulo_principal longo ({len(palavras)} palavras), truncado")
        titulo = " ".join(palavras[:6])

    # 3. Ponto final
    if titulo.endswith("."):
        titulo = titulo[:-1].strip()
        alertas.append("ponto final removido do titulo_principal")

    # 4. Palavras proibidas
    titulo_lower = titulo.lower()
    for proibida in _PALAVRAS_PROIBIDAS_ARTE:
        if proibida in titulo_lower:
            alertas.append(f"palavra proibida '{proibida}' no titulo_principal — fallback")
            titulo = _fallback_titulo_arte(fatos)
            break

    # 5. "grátis/gratuito" sem confirmação
    gratuito_confirmado = fatos.get("gratuito") is True
    if not gratuito_confirmado:
        for termo in ("gratuito", "grátis", "entrada franca"):
            if termo in titulo.lower():
                alertas.append(f"'{termo}' no título sem gratuito=true nos fatos — fallback")
                titulo = _fallback_titulo_arte(fatos)
                break
            if termo in linha.lower():
                alertas.append(f"'{termo}' na linha de apoio sem gratuito=true — removido")
                linha = _fallback_linha_arte(fatos)
                break

    # 6. Igual ao título do release
    if release_titulo and titulo.lower().strip() == release_titulo.lower().strip():
        alertas.append("titulo_principal igual ao release — fallback")
        titulo = _fallback_titulo_arte(fatos)

    # 7. Linha de apoio: máx 12 palavras
    if linha and len(linha.split()) > 12:
        alertas.append(f"linha_apoio longa ({len(linha.split())} palavras), truncada")
        linha = " ".join(linha.split()[:12])

    # 8. Badge: máx 2 palavras
    if badge and len(badge.split()) > 2:
        alertas.append(f"badge longo ('{badge}'), truncado")
        badge = " ".join(badge.split()[:2])
    if not badge:
        badge = fatos.get("categoria_editorial", "CULTURA").upper()

    return {**arte, "titulo_principal": titulo, "linha_apoio": linha, "badge": badge}, alertas


def _erros_criticos_arte(arte: dict, fatos: dict, release_titulo: str = "") -> list[str]:
    """
    Retorna lista de erros críticos que justificam retentativa ao LLM.
    Erros críticos: campo vazio, palavra proibida, gratuidade não confirmada.
    Erros menores (longo, ponto final) são corrigidos deterministicamente.
    """
    erros = []
    titulo = arte.get("titulo_principal", "").strip()
    linha  = arte.get("linha_apoio", "").strip()

    if not titulo:
        erros.append("titulo_principal está vazio")
    else:
        titulo_lower = titulo.lower()
        for proibida in _PALAVRAS_PROIBIDAS_ARTE:
            if proibida in titulo_lower:
                erros.append(f"titulo_principal contém '{proibida}' — proibido")
                break
        if "#" in titulo:
            erros.append("titulo_principal contém hashtag — proibido")
        gratuito_confirmado = fatos.get("gratuito") is True
        if not gratuito_confirmado:
            for termo in ("gratuito", "grátis", "entrada franca"):
                if termo in titulo_lower:
                    erros.append(f"titulo_principal usa '{termo}' sem gratuito confirmado")
                    break
        if release_titulo and titulo.lower() == release_titulo.lower():
            erros.append("titulo_principal é igual ao título do release")

    if not linha:
        erros.append("linha_apoio está vazia")
    elif "#" in linha:
        erros.append("linha_apoio contém hashtag — proibido")

    if not arte.get("badge", "").strip():
        erros.append("badge está vazio")

    return erros


def gerar_arte_com_validacao(
    release_text: str,
    fatos: dict,
    avaliacao: dict,
    sender: str = "",
    release_titulo: str = "",
) -> dict:
    """
    Gera conteúdo editorial com loop de validação para texto_arte.
    Tenta até 2 vezes: na segunda, passa os erros como feedback explícito ao LLM.
    Se ambas falharem, aplica fallback determinístico.
    Retorna o dict completo de gerar_conteudo com texto_arte validado.
    """
    from llm_call import llm_call_json

    # Tentativa 1: geração normal
    post = gerar_conteudo(release_text, fatos, avaliacao, sender=sender)
    arte = post.get("texto_arte", {})
    erros = _erros_criticos_arte(arte, fatos, release_titulo)

    if erros:
        print(f"[editorial] texto_arte com {len(erros)} erro(s) crítico(s): {erros}", file=sys.stderr)
        print(f"[editorial] Tentativa 2 com feedback explícito...", file=sys.stderr)

        # Tentativa 2: inclui feedback dos erros no prompt
        angulo = avaliacao.get("angulo_recomendado", "")
        angulo_instrucao = f"ÂNGULO EDITORIAL: {angulo}\n\n" if angulo else ""
        feedback = "\n".join(f"- {e}" for e in erros)

        system_retry = f"""{angulo_instrucao}{_VOZ_EDITORIAL}

Na tentativa anterior, o campo texto_arte falhou com estes erros:
{feedback}

Corrija APENAS o campo texto_arte. Os outros campos podem ser os mesmos.

Regras do texto_arte:
- badge: 1 ou 2 palavras em maiúsculas, sem hashtag
- titulo_principal: máx 6 palavras, sem ponto final, sem hashtag, sem palavras proibidas
- linha_apoio: máx 12 palavras, sem hashtag
- NUNCA usar hashtags em nenhum campo
- só mencionar gratuidade se gratuito=true nos fatos

Fatos: {json.dumps(fatos, ensure_ascii=False)}

Retorne APENAS o objeto texto_arte corrigido em JSON:
{{
  "template": "ameriafro_v3",
  "badge": "",
  "titulo_principal": "",
  "linha_apoio": "",
  "alerta": ""
}}"""

        try:
            arte_retry = llm_call_json(system=system_retry, user=f"Release:\n{release_text[:3000]}", model=EDITORIAL_MODEL)
            if isinstance(arte_retry, dict) and arte_retry.get("titulo_principal"):
                erros2 = _erros_criticos_arte(arte_retry, fatos, release_titulo)
                if not erros2:
                    post["texto_arte"] = arte_retry
                    print(f"[editorial] texto_arte corrigido na tentativa 2.", file=sys.stderr)
                    arte = arte_retry
                else:
                    print(f"[editorial] Tentativa 2 ainda com erros: {erros2} — aplicando fallback.", file=sys.stderr)
        except Exception as e:
            print(f"[editorial] Tentativa 2 falhou ({e}) — aplicando fallback.", file=sys.stderr)

    # Fallback determinístico se ainda houver erros
    arte_final, alertas = validar_arte(post.get("texto_arte", {}), fatos, release_titulo)
    if alertas:
        print(f"[editorial] validar_arte aplicou correções: {alertas}", file=sys.stderr)
    post["texto_arte"] = arte_final
    return post
