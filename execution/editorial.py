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


def extract_editorial_hierarchy(release_text: str, fatos: dict) -> dict:
    """
    Classifica informações do release em hierarquia editorial.
    Define foco_principal, serviço, atividades passadas e ângulo para arte/legenda.
    """
    from llm_call import llm_call_json

    _FALLBACK = {
        "foco_principal": fatos.get("resumo_factual", ""),
        "servico_principal": {
            "evento": fatos.get("projeto", ""),
            "cidade": fatos.get("cidade", ""),
            "local": fatos.get("local", ""),
            "endereco": fatos.get("endereco", ""),
            "datas": [fatos.get("data", "")] if fatos.get("data") else [],
            "horarios": [fatos.get("horario", "")] if fatos.get("horario") else [],
            "entrada": "gratuita" if fatos.get("gratuito") else fatos.get("valor", ""),
            "atividade": "",
            "publico": fatos.get("publico_alvo", ""),
        },
        "eventos_futuros_ou_ativos": [],
        "contexto_secundario": [],
        "atividades_passadas": [],
        "nao_usar_como_foco": [],
        "angulo_instagram_recomendado": fatos.get("resumo_factual", ""),
        "angulo_arte_recomendado": fatos.get("resumo_factual", ""),
        "motivo_da_priorizacao": "extração automática de fallback",
    }

    system = """Você é editor do +blog.

Sua função é organizar a hierarquia editorial de um release para definir o foco correto da arte e da legenda de Instagram.

Nem todo fato do release tem o mesmo peso.

Priorize:
- o assunto principal do título;
- o serviço principal;
- eventos futuros ou ainda úteis para o público;
- informações com data, horário, local e entrada;
- o que o público ainda pode fazer, acompanhar ou participar.

Rebaixe:
- atividades já realizadas;
- contexto institucional;
- histórico do projeto;
- informações de apoio;
- detalhes que não representam o foco principal.

Use somente informações do release e dos fatos extraídos.

Regras:
- Se uma atividade já aconteceu, coloque em atividades_passadas.
- Não use atividade passada como foco de Instagram.
- Se o release tem seção "Serviço", ela deve ter peso alto.
- O foco da arte e da legenda deve vir do serviço principal.
- O título da arte deve refletir o que o público ainda pode acompanhar ou saber.
- Não escolha como foco uma frase bonita se ela não representa o serviço principal.
- Não transforme contexto secundário em chamada principal.

Responda apenas em JSON válido:
{
  "foco_principal": "",
  "servico_principal": {
    "evento": "",
    "cidade": "",
    "local": "",
    "endereco": "",
    "datas": [],
    "horarios": [],
    "entrada": "",
    "atividade": "",
    "publico": ""
  },
  "eventos_futuros_ou_ativos": [],
  "contexto_secundario": [],
  "atividades_passadas": [],
  "nao_usar_como_foco": [],
  "angulo_instagram_recomendado": "",
  "angulo_arte_recomendado": "",
  "motivo_da_priorizacao": ""
}"""

    fatos_str = json.dumps(fatos, ensure_ascii=False, indent=2)
    user = f"Fatos extraídos:\n{fatos_str}\n\nRelease:\n{release_text[:5000]}"

    try:
        result = llm_call_json(system=system, user=user, model=EDITORIAL_MODEL)
        if isinstance(result, dict) and result.get("foco_principal"):
            return {**_FALLBACK, **result}
        return _FALLBACK
    except Exception as e:
        print(f"[editorial] extract_editorial_hierarchy falhou: {e}", file=sys.stderr)
        return _FALLBACK


def validate_instagram_output_against_hierarchy(
    arte: dict,
    legenda: dict,
    hierarchy: dict,
    fatos: dict,
) -> list[str]:
    """
    Verifica se arte e legenda respeitam a hierarquia editorial.
    Retorna lista de erros — vazia significa que está OK.
    """
    erros = []
    nao_usar = [t.lower() for t in hierarchy.get("nao_usar_como_foco", [])]
    passadas = [t.lower() for t in hierarchy.get("atividades_passadas", [])]

    titulo = arte.get("titulo_principal", "").lower()
    linha = arte.get("linha_apoio", "").lower()
    curta = legenda.get("legenda_curta", "").lower()
    contexto = legenda.get("legenda_contexto", "").lower()
    legenda_full = curta + "\n" + contexto

    # 1. Arte ou legenda usa termo da lista nao_usar_como_foco?
    for termo in nao_usar:
        if len(termo) > 4:  # ignora palavras muito curtas
            if termo in titulo or termo in linha:
                erros.append(f"arte usa '{termo}' — listado em nao_usar_como_foco")
            if termo in legenda_full:
                erros.append(f"legenda usa '{termo}' — listado em nao_usar_como_foco")

    # 2. Legenda abre com atividade passada?
    if passadas:
        primeiros = curta[:200].lower()
        for passada in passadas:
            if len(passada) > 8 and passada[:30] in primeiros:
                erros.append(f"legenda abre com atividade passada: '{passada[:50]}'")

    # 3. Hashtag indevida
    if "#" in arte.get("titulo_principal", "") or "#" in arte.get("linha_apoio", ""):
        erros.append("arte contém hashtag")
    if "#" in legenda_full:
        erros.append("legenda contém hashtag")

    # 4. Gratuidade não confirmada
    if fatos.get("gratuito") is not True:
        for campo in (titulo, linha, curta[:300]):
            for termo in ("gratuito", "grátis", "entrada franca"):
                if termo in campo:
                    erros.append(f"usa '{termo}' sem gratuidade confirmada")
                    break

    return erros


def gerar_conteudo(
    release_text: str,
    fatos: dict,
    avaliacao: dict,
    sender: str = "",
    hierarchy: dict | None = None,
) -> dict:
    """
    Gera o conteúdo editorial completo do post.
    sender: usado como fallback para creditos_wordpress.texto.
    hierarchy: hierarquia editorial para guiar arte e foco.
    """
    from llm_call import llm_call_json

    angulo = avaliacao.get("angulo_recomendado", "")
    angulo_instrucao = f"ÂNGULO EDITORIAL: {angulo}\n\n" if angulo else ""

    # Injeta contexto de hierarquia no prompt se disponível
    hierarchy_instrucao = ""
    if hierarchy and hierarchy.get("foco_principal"):
        nao_usar_str = "\n".join(f"  - {t}" for t in hierarchy.get("nao_usar_como_foco", []))
        passadas_str = "\n".join(f"  - {t}" for t in hierarchy.get("atividades_passadas", []))
        hierarchy_instrucao = f"""
════════════════════════════════
HIERARQUIA EDITORIAL (OBRIGATÓRIO)
════════════════════════════════
FOCO PRINCIPAL: {hierarchy.get("foco_principal", "")}
ÂNGULO PARA ARTE: {hierarchy.get("angulo_arte_recomendado", "")}
ÂNGULO PARA INSTAGRAM: {hierarchy.get("angulo_instagram_recomendado", "")}

NÃO USAR COMO FOCO (proibido virar título ou abertura):
{nao_usar_str or "  (nenhum)"}

ATIVIDADES JÁ REALIZADAS (só como contexto secundário, nunca como foco):
{passadas_str or "  (nenhuma)"}

A arte e a legenda DEVEM refletir o foco principal acima.
A arte e a legenda NÃO PODEM usar qualquer item da lista "NÃO USAR COMO FOCO".
"""

    system = f"""{angulo_instrucao}{hierarchy_instrucao}{_VOZ_EDITORIAL}

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
- A arte deve refletir o FOCO PRINCIPAL definido na hierarquia editorial acima.
- Não use atividades passadas como título da arte.
- Não use contexto secundário como chamada principal.
- Não use nenhum termo listado em "NÃO USAR COMO FOCO".
- badge: 1 ou 2 palavras em maiúsculas (ex: "LITERATURA", "MÚSICA", "CULTURA")
- titulo_principal: máx 6 palavras, SEM ponto final, SEM hashtags (#)
- titulo_principal NÃO pode ser igual ao titulo_site
- titulo_principal NÃO pode conter: "imperdível", "confira", "não perca", "vem aí", "promete", "programação especial", "acontece em"
- linha_apoio: máx 12 palavras, sem ponto final, sem hashtag, não repetir o título
- NUNCA usar hashtags (#) em nenhum campo de texto_arte
- só usar "gratuito" ou "grátis" se gratuito=true nos fatos extraídos
- só mencionar cidade, data ou local se estiverem nos fatos extraídos
- titulo_principal deve parecer manchete de post social, não frase de release:
    CERTO: "Histórias no CEU", "Leitura ganha asas", "Cultura preta na Estação"
    ERRADO: "Projeto leva magia da leitura para crianças", "Cantigas que unem gerações"

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


def gerar_legenda(
    fatos: dict,
    resumo: str,
    arte_instagram: dict | None = None,
    hierarchy: dict | None = None,
) -> dict:
    """
    Gera legenda para Instagram com 4-6 blocos, narrativa editorial, sem hashtags.
    arte_instagram: dict com titulo_principal/linha_apoio/badge — evita repetir texto da arte.
    hierarchy: hierarquia editorial para guiar foco e evitar termos proibidos.
    Sem créditos — créditos são exclusivos do HTML WordPress.
    """
    from llm_call import llm_call_json

    _FALLBACK_servico = hierarchy.get("servico_principal", {}) if hierarchy else {}
    _fallback_contexto = ""
    if _FALLBACK_servico.get("evento"):
        datas_str = " e ".join(_FALLBACK_servico.get("datas", []))
        horarios_str = " e ".join(_FALLBACK_servico.get("horarios", []))
        _fallback_contexto = (
            f"{_FALLBACK_servico.get('evento', '')} realiza sessões em {_FALLBACK_servico.get('cidade', '')}.\n\n"
            + (f"A programação acontece nos dias {datas_str}" if datas_str else "")
            + (f", às {horarios_str}" if horarios_str else "")
            + (f", no {_FALLBACK_servico.get('local', '')}" if _FALLBACK_servico.get("local") else "")
            + ".\n\nNo +blog tem os detalhes para você se organizar."
        )

    _FALLBACK = {
        "legenda_curta": (
            "Tem programação cultural chegando por aqui.\n\n"
            "A gente reuniu no +blog as informações confirmadas para você entender melhor o que vai rolar.\n\n"
            "Vale salvar e mandar para quem curte esse tipo de programação na região."
        ),
        "legenda_contexto": _fallback_contexto,
        "cta_sugerido": "",
    }

    arte = arte_instagram or {}
    arte_str = ""
    if arte.get("titulo_principal"):
        arte_str = (
            f"badge: {arte.get('badge', '')}\n"
            f"titulo: {arte.get('titulo_principal', '')}\n"
            f"linha_apoio: {arte.get('linha_apoio', '')}"
        )

    fatos_str = json.dumps(fatos, ensure_ascii=False, indent=2)

    # Bloco de hierarquia editorial para o prompt
    hierarchy_str = ""
    if hierarchy and hierarchy.get("foco_principal"):
        nao_usar_str = "\n".join(f"  - {t}" for t in hierarchy.get("nao_usar_como_foco", []))
        passadas_str = "\n".join(f"  - {t}" for t in hierarchy.get("atividades_passadas", []))
        hierarchy_str = f"""
HIERARQUIA EDITORIAL — SIGA OBRIGATORIAMENTE:
Foco principal: {hierarchy.get("foco_principal", "")}
Ângulo recomendado: {hierarchy.get("angulo_instagram_recomendado", "")}

NÃO USAR COMO FOCO (proibido virar abertura ou tema principal):
{nao_usar_str or "  (nenhum)"}

ATIVIDADES JÁ REALIZADAS (só como contexto secundário, nunca como abertura):
{passadas_str or "  (nenhuma)"}

A legenda DEVE abrir com o foco principal.
A legenda NÃO PODE abrir com atividade passada.
A legenda NÃO PODE transformar contexto secundário em tema principal.
"""

    system = f"""{_VOZ_EDITORIAL}

Você é social media e editor do +blog.

Crie duas versões de legenda para Instagram com linguagem leve, humana, regional e natural.

O +blog fala com pessoas de Americana, Santa Bárbara d'Oeste, Nova Odessa e Sumaré que querem descobrir eventos, cultura, lazer e boas experiências na região.

A legenda precisa ter cara de Instagram de verdade.
Ela não deve parecer release.
Ela não deve parecer resumo frio de matéria.
Ela não deve ser institucional.
Ela não deve repetir mecanicamente o texto da arte.
Ela NÃO deve ter hashtags — nenhuma sequer.
{hierarchy_str}

ESTRUTURA OBRIGATÓRIA — 4 a 6 blocos curtos:

1. Abertura curta e natural — uma frase leve que puxe atenção sem "Vem aí" nem "Confira".
2. Contexto do evento/projeto — o que é, onde acontece.
3. Informações de serviço — data, horário, local, gratuidade e público quando confirmados.
4. Camada editorial — por que isso importa para a cidade, a cultura, a região ou quem acompanha o portal.
5. CTA social — salvar, mandar para alguém, marcar alguém ou comentar, conforme o conteúdo.
6. CTA para o portal — convidar a acessar o +blog de forma natural (só se fizer sentido).

TAMANHO:
- legenda_curta: 3 a 4 blocos curtos
- legenda_contexto: 5 a 6 blocos curtos — com mais narrativa e camada editorial

REFERÊNCIA DE ESTILO (inspire-se no tom e ritmo, não copie):
"Tem história chegando no CEU das Artes

Nos dias 12 e 13 de maio, o projeto Nas Asas da Leitura passa por Santa Bárbara com sessões gratuitas de contação de histórias para crianças e público em geral

A programação acontece em dois horários, às 9h30 e às 13h30, com Valter Valverde, Renata de Paula e outros contadores conduzindo as atividades

É aquele tipo de programação simples, bonita e necessária: aproxima as crianças da leitura, movimenta os espaços públicos e cria memória boa na cidade

Se você conhece alguém que curte programação cultural para crianças, já manda esse post

No +blog tem mais detalhes para você se organizar antes de ir"

REGRAS ABSOLUTAS:
- NUNCA usar hashtags (#) — nem uma sequer em nenhum campo
- não inventar data, horário, local, cidade, valor, gratuidade, atrações ou participantes
- não repetir mecanicamente o texto da arte
- não usar "imperdível", "confira", "experiência mágica", "incrível" (elogio genérico)
- não usar linguagem institucional
- sem créditos de texto ou fotos
- sem mencionar assessoria ou fonte
- frases curtas e fluidas, com ritmo de Instagram
- CTA variado — não usar sempre a mesma frase

Retorne APENAS um objeto JSON válido:
{{
  "legenda_curta": "3 a 4 blocos curtos. SEM hashtags.",
  "legenda_contexto": "5 a 6 blocos com mais narrativa e camada editorial. SEM hashtags.",
  "cta_sugerido": "o CTA social escolhido"
}}"""

    user_parts = [f"Fatos confirmados:\n{fatos_str}", f"Resumo da matéria:\n{resumo[:600]}"]
    if arte_str:
        user_parts.append(f"Texto da arte (não repetir mecanicamente):\n{arte_str}")
    user = "\n\n".join(user_parts)

    def _limpar_hashtags(texto: str) -> str:
        """Remove linhas que são apenas hashtags e tokens # soltos."""
        linhas = [l for l in texto.splitlines() if not l.strip().startswith("#")]
        return "\n".join(linhas)

    def _blocos(texto: str) -> int:
        """Conta blocos/parágrafos separados por linha em branco."""
        return len([b for b in texto.split("\n\n") if b.strip()])

    def _valida_legenda(result: dict) -> list[str]:
        erros = []
        ctx = result.get("legenda_contexto", "")
        if "#" in result.get("legenda_curta", "") or "#" in ctx:
            erros.append("contém hashtag")
        for proibida in ("imperdível", "confira", "experiência mágica"):
            if proibida in ctx.lower() or proibida in result.get("legenda_curta", "").lower():
                erros.append(f"contém '{proibida}'")
        if _blocos(ctx) < 4:
            erros.append(f"legenda_contexto tem apenas {_blocos(ctx)} bloco(s) — mínimo 4")
        return erros

    try:
        result = llm_call_json(system=system, user=user, model=EDITORIAL_MODEL)
        if not (isinstance(result, dict) and result.get("legenda_curta")):
            return _FALLBACK

        # Limpeza defensiva de hashtags
        for campo in ("legenda_curta", "legenda_contexto"):
            if campo in result:
                result[campo] = _limpar_hashtags(result[campo])
        result.pop("hashtags", None)

        # Validação — retentativa se legenda_contexto curta demais ou com erros
        erros = _valida_legenda(result)
        if erros:
            print(f"[editorial] legenda com problema(s): {erros} — retentativa com feedback.", file=sys.stderr)
            feedback = "; ".join(erros)
            user_retry = (
                f"{user}\n\n"
                f"FEEDBACK DA VALIDAÇÃO: a legenda anterior foi rejeitada por: {feedback}.\n"
                f"Reescreva com mais contexto, ritmo e camada editorial, mantendo apenas informações confirmadas.\n"
                f"legenda_contexto deve ter pelo menos 5 blocos separados por linha em branco. Sem hashtags."
            )
            try:
                result2 = llm_call_json(system=system, user=user_retry, model=EDITORIAL_MODEL)
                if isinstance(result2, dict) and result2.get("legenda_curta"):
                    for campo in ("legenda_curta", "legenda_contexto"):
                        if campo in result2:
                            result2[campo] = _limpar_hashtags(result2[campo])
                    result2.pop("hashtags", None)
                    erros2 = _valida_legenda(result2)
                    if not erros2:
                        print(f"[editorial] legenda corrigida na retentativa.", file=sys.stderr)
                        return result2
                    else:
                        print(f"[editorial] retentativa ainda com erros: {erros2} — usando resultado original.", file=sys.stderr)
            except Exception as e2:
                print(f"[editorial] retentativa de legenda falhou ({e2}).", file=sys.stderr)

        return result

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
    hierarchy: dict | None = None,
) -> dict:
    """
    Gera conteúdo editorial com loop de validação para texto_arte.
    Tenta até 2 vezes: na segunda, passa os erros como feedback explícito ao LLM.
    Se ambas falharem, aplica fallback determinístico.
    hierarchy: hierarquia editorial para guiar o foco da arte.
    Retorna o dict completo de gerar_conteudo com texto_arte validado.
    """
    from llm_call import llm_call_json

    # Tentativa 1: geração com hierarquia
    post = gerar_conteudo(release_text, fatos, avaliacao, sender=sender, hierarchy=hierarchy)
    arte = post.get("texto_arte", {})
    erros = _erros_criticos_arte(arte, fatos, release_titulo)

    # Adiciona verificação de hierarquia aos erros críticos
    if hierarchy:
        nao_usar = [t.lower() for t in hierarchy.get("nao_usar_como_foco", [])]
        titulo_lower = arte.get("titulo_principal", "").lower()
        for termo in nao_usar:
            if len(termo) > 4 and termo in titulo_lower:
                erros.append(f"titulo_principal usa '{termo}' — proibido pela hierarquia editorial")
                break

    if erros:
        print(f"[editorial] texto_arte com {len(erros)} erro(s) crítico(s): {erros}", file=sys.stderr)
        print(f"[editorial] Tentativa 2 com feedback explícito...", file=sys.stderr)

        # Tentativa 2: inclui feedback dos erros e hierarquia no prompt
        angulo = avaliacao.get("angulo_recomendado", "")
        angulo_instrucao = f"ÂNGULO EDITORIAL: {angulo}\n\n" if angulo else ""
        feedback = "\n".join(f"- {e}" for e in erros)

        hierarchy_retry_str = ""
        if hierarchy and hierarchy.get("foco_principal"):
            nao_usar_str = "\n".join(f"  - {t}" for t in hierarchy.get("nao_usar_como_foco", []))
            hierarchy_retry_str = f"""
FOCO PRINCIPAL OBRIGATÓRIO: {hierarchy.get("foco_principal", "")}
ÂNGULO PARA ARTE: {hierarchy.get("angulo_arte_recomendado", "")}
NÃO USAR COMO FOCO: {nao_usar_str or "(nenhum)"}
"""

        system_retry = f"""{angulo_instrucao}{_VOZ_EDITORIAL}
{hierarchy_retry_str}
Na tentativa anterior, o campo texto_arte falhou com estes erros:
{feedback}

Corrija APENAS o campo texto_arte usando o foco principal acima como base.

Regras do texto_arte:
- badge: 1 ou 2 palavras em maiúsculas, sem hashtag
- titulo_principal: máx 6 palavras, sem ponto final, sem hashtag, sem palavras proibidas
- titulo_principal deve refletir o foco principal — não use atividades passadas nem itens proibidos
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
