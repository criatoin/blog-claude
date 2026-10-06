"""
editorial_checagem.py — Laço checa → corrige → checa da matéria.

A checagem em si (código + Jev) fica em fact_check.py. Aqui só a orquestração:
quando há problema factual em campo corrigível, o modelo criativo reescreve só
aqueles trechos e a matéria é checada de novo (até MAX_CORRECOES vezes).
"""

import json
import sys

import editorial as _ed
import fact_check as _fc
import llm_call as _llm

MAX_CORRECOES = 2


def corrigir_texto(release_text: str, post: dict, problemas: list[dict]) -> dict:
    """
    Reescreve só o que o fact_check apontou, usando o modelo criativo.
    Retorna {titulo_site, subtitulo, resumo_telegram, html} corrigidos,
    ou {} se a correção falhar (o chamador mantém o texto anterior).
    """
    lista = "\n".join(f'- [{p["campo"]}] "{p["trecho"]}": {p["motivo"]}' for p in problemas)
    atual = {k: post.get(k, "") for k in _fc.CAMPOS_CORRIGIVEIS}

    system = f"""{_ed._VOZ_EDITORIAL}

Você está corrigindo uma matéria já escrita. Um checador comparou cada frase com o
release (fonte da verdade) e encontrou os problemas listados pelo usuário. Para cada um:
- se o dado existe no release com outro valor, use o valor do release;
- se o dado não existe no release, remova a informação — nunca invente um substituto.
Não mexa no resto do texto. Mantenha HTML puro (sem Markdown) e o tamanho aproximado.

Retorne APENAS um objeto JSON com as chaves:
{{"titulo_site": "...", "subtitulo": "...", "resumo_telegram": "...", "html": "..."}}"""

    user = f"""Problemas encontrados:
{lista}

Release original:
{release_text[:6000]}

Matéria atual:
{json.dumps(atual, ensure_ascii=False)}"""

    try:
        result = _llm.llm_call_json(system=system, user=user, model=_llm.creative_model(), max_tokens=8192)
    except Exception as e:
        print(f"[editorial] corrigir_texto falhou: {e}", file=sys.stderr)
        return {}
    if not isinstance(result, dict):
        return {}
    if len(str(result.get("html", ""))) < 0.5 * len(atual["html"]):
        print("[editorial] corrigir_texto devolveu HTML curto demais — mantendo o original", file=sys.stderr)
        return {}
    return {k: str(result[k]) if k in result else atual[k] for k in _fc.CAMPOS_CORRIGIVEIS}


def checar_e_corrigir(release_text: str, post: dict, legenda: str = "") -> tuple[dict, dict]:
    """
    Checa a matéria (fact_check: código + Jev). Se houver problema em campo
    corrigível, pede reescrita e checa de novo — até MAX_CORRECOES vezes.
    Problemas na arte ou na legenda não são reescritos: vão como alerta no card.
    Retorna (post_final, checagem_final).
    """
    checagem = _fc.verificar_post(release_text, post, legenda)
    for tentativa in range(1, MAX_CORRECOES + 1):
        problemas = [b for b in checagem["bloqueantes"] if b["campo"] in _fc.CAMPOS_CORRIGIVEIS]
        if not problemas:
            break
        print(f"[editorial] Correção {tentativa}/{MAX_CORRECOES}: {len(problemas)} problema(s) factual(is)",
              file=sys.stderr)
        corrigido = corrigir_texto(release_text, post, problemas)
        if not corrigido:
            break
        post = {**post, **corrigido}
        checagem = _fc.verificar_post(release_text, post, legenda)
    return post, checagem


def resumo_telegram(post: dict, checagem: dict, avaliacao: dict) -> dict:
    """
    Monta o resumo para o card do Telegram a partir de dados já gerados.
    Zero LLM calls.
    """
    alertas = []
    if post.get("_fallback"):
        alertas.append(post["_fallback"])
    for p in (checagem.get("bloqueantes") or []) + (checagem.get("alertas") or []):
        alertas.append(f"{p['trecho'][:60]}: {p['motivo']}" if p.get("trecho") else p["motivo"])

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
        "checagem": _fc.linha_card(checagem),
    }
