# Revisão do Sistema Autônomo +blog — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tornar o pipeline autônomo confiável: pautas com fontes reais, modelo criativo para escrita, gate humano de imagens no Telegram, arte IG com diagramação correta e remoção do Google Sheets.

**Architecture:** Scripts Python determinísticos em `execution/` orquestrados por pipelines (`run_releases.py`, `run_pauta_generate.py`, `run_pauta_produce.py`) + daemon `telegram_bot.py`. LLM via OpenRouter (`llm_call.py`). Estado em `.tmp/*.json`. WordPress via REST. Spec: `docs/superpowers/specs/2026-07-15-revisao-sistema-blog-design.md`.

**Tech Stack:** Python 3.11, requests, Pillow, pytest 8.3, OpenRouter API (DeepSeek + Gemini 2.5 Flash), Tavily, Telegram Bot API, WordPress REST API.

## Global Constraints

- Env vars novas: `CREATIVE_MODEL` (padrão exato: `google/gemini-2.5-flash`). Env vars removidas ao final: `SHEETS_ID`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`, `SHEETS_TOKEN_B64`.
- Arte IG: 1080×1350 WebP < 1MB; título em ≤ 3 linhas, fonte entre 60 e 92pt, largura máx de linha 944px.
- Nunca publicar placeholder ou imagem não validada sem aprovação humana.
- Fallbacks de LLM nunca seguem silenciosamente: viram alerta ⚠️ no card do Telegram.
- Testes: `python -m pytest tests/ -v` a partir da raiz do projeto. Scripts importam módulos irmãos via `sys.path.insert(0, .../execution)`.
- Commits frequentes, mensagens em português no padrão do repo (`fix:`/`feat:`), com `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- O container em produção continua rodando durante a implementação; nada é deployado até o final.

---

### Task 1: `llm_call.py` — JSON forçado pela API + modelo criativo

**Files:**
- Modify: `execution/llm_call.py`
- Test: `tests/test_llm_call.py` (criar)

**Interfaces:**
- Produces: `llm_call(system, user, model=None, temperature=0.3, max_tokens=4096, json_mode=False) -> str`; `llm_call_json(system, user, model=None) -> dict | list` (agora envia `response_format={"type":"json_object"}`); `creative_model() -> str` (lê env `CREATIVE_MODEL`, padrão `google/gemini-2.5-flash`).

- [ ] **Step 1: Escrever testes que falham**

Criar `tests/test_llm_call.py`:

```python
"""Testa json_mode e creative_model de llm_call."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "execution"))


def test_json_mode_envia_response_format(monkeypatch):
    import llm_call as lc

    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": '{"ok": true}'}}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return FakeResp()

    monkeypatch.setattr(lc.requests, "post", fake_post)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    result = lc.llm_call_json(system="s", user="u")
    assert result == {"ok": True}
    assert captured["payload"]["response_format"] == {"type": "json_object"}


def test_sem_json_mode_nao_envia_response_format(monkeypatch):
    import llm_call as lc

    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "texto"}}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return FakeResp()

    monkeypatch.setattr(lc.requests, "post", fake_post)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    lc.llm_call(system="s", user="u")
    assert "response_format" not in captured["payload"]


def test_creative_model_padrao(monkeypatch):
    import llm_call as lc
    monkeypatch.delenv("CREATIVE_MODEL", raising=False)
    assert lc.creative_model() == "google/gemini-2.5-flash"


def test_creative_model_env(monkeypatch):
    import llm_call as lc
    monkeypatch.setenv("CREATIVE_MODEL", "anthropic/claude-haiku-4.5")
    assert lc.creative_model() == "anthropic/claude-haiku-4.5"
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `python -m pytest tests/test_llm_call.py -v`
Expected: FAIL — `AttributeError: module 'llm_call' has no attribute 'creative_model'` e/ou asserts de `response_format`.

- [ ] **Step 3: Implementar em `execution/llm_call.py`**

3a. Assinatura de `llm_call` (linha 35) ganha `json_mode: bool = False`:

```python
def llm_call(
    system: str,
    user: str,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    json_mode: bool = False,
) -> str:
```

3b. Após montar `payload` (linha 70-78), adicionar:

```python
    if json_mode:
        # Força a API a devolver JSON válido (structured output do OpenRouter)
        payload["response_format"] = {"type": "json_object"}
```

3c. Em `llm_call_json` (linha 137), trocar a primeira linha por:

```python
    raw = llm_call(system=system, user=user, model=model, json_mode=True)
```

3d. Adicionar após `DEFAULT_MODEL` (linha 30):

```python
DEFAULT_CREATIVE_MODEL = "google/gemini-2.5-flash"


def creative_model() -> str:
    """Modelo para tarefas de escrita criativa (legenda, arte, HTML, curadoria)."""
    return os.getenv("CREATIVE_MODEL", DEFAULT_CREATIVE_MODEL)
```

Manter todo o reparo de JSON existente em `llm_call_json` — vira último recurso.

- [ ] **Step 4: Rodar testes**

Run: `python -m pytest tests/test_llm_call.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add execution/llm_call.py tests/test_llm_call.py
git commit -m "feat: json_mode via response_format + creative_model() em llm_call"
```

---

### Task 2: `editorial.py` — rotear tarefas criativas + fallback sinalizado

**Files:**
- Modify: `execution/editorial.py`
- Test: `tests/test_editorial.py` (criar)

**Interfaces:**
- Consumes: `creative_model()` de Task 1.
- Produces: `gerar_conteudo(...)` e `gerar_legenda(...)` chamam LLM com `model=creative_model()`. Dicts de fallback de `gerar_legenda` e `gerar_conteudo` ganham chave `"_fallback": "<motivo>"`. Funções mecânicas (`extrair_fatos`, `avaliar_relevancia`, `extract_editorial_hierarchy`, `validar_fatos`) seguem com `EDITORIAL_MODEL`.

- [ ] **Step 1: Escrever teste que falha**

Criar `tests/test_editorial.py`:

```python
"""Testa roteamento de modelo e sinalização de fallback em editorial."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "execution"))


def test_gerar_legenda_usa_modelo_criativo(monkeypatch):
    import editorial
    import llm_call as lc

    captured = {}

    def fake_llm_call_json(system, user, model=None):
        captured["model"] = model
        return {
            "legenda_curta": "a.\n\nb.\n\nc.\n\nd.",
            "legenda_contexto": "a.\n\nb.\n\nc.\n\nd.\n\ne.",
            "cta_sugerido": "x",
        }

    monkeypatch.setattr(lc, "llm_call_json", fake_llm_call_json)
    monkeypatch.delenv("CREATIVE_MODEL", raising=False)

    result = editorial.gerar_legenda({"gratuito": True}, "resumo")
    assert captured["model"] == "google/gemini-2.5-flash"
    assert "_fallback" not in result


def test_gerar_legenda_fallback_sinalizado(monkeypatch):
    import editorial
    import llm_call as lc

    def fake_llm_call_json(system, user, model=None):
        raise RuntimeError("api fora do ar")

    monkeypatch.setattr(lc, "llm_call_json", fake_llm_call_json)

    result = editorial.gerar_legenda({}, "resumo")
    assert result.get("_fallback"), "fallback deve vir sinalizado com motivo"


def test_gerar_conteudo_fallback_sinalizado(monkeypatch):
    import editorial
    import llm_call as lc

    def fake_llm_call_json(system, user, model=None):
        raise RuntimeError("api fora do ar")

    monkeypatch.setattr(lc, "llm_call_json", fake_llm_call_json)

    result = editorial.gerar_conteudo("release", {}, {})
    assert result.get("_fallback")
```

**Nota de implementação:** `editorial.py` hoje importa `from llm_call import llm_call_json` *dentro* de cada função. Para o monkeypatch acima funcionar, a implementação (Step 3) troca esses imports internos por chamadas via módulo: `import llm_call` no topo do arquivo e `llm_call.llm_call_json(...)` nos call sites.

- [ ] **Step 2: Rodar e confirmar falha**

Run: `python -m pytest tests/test_editorial.py -v`
Expected: FAIL (model é None / `_fallback` ausente).

- [ ] **Step 3: Implementar em `execution/editorial.py`**

3a. Topo do arquivo (após linha 14), adicionar import e remover os `from llm_call import llm_call_json` internos de todas as funções:

```python
import llm_call as _llm

EDITORIAL_MODEL = os.getenv("EDITORIAL_MODEL", "deepseek/deepseek-chat")
```

Substituir em TODAS as funções `llm_call_json(...)` por `_llm.llm_call_json(...)`.

3b. Roteamento: nas funções criativas, trocar `model=EDITORIAL_MODEL` por `model=_llm.creative_model()`:
- `gerar_conteudo` (linha 444)
- `gerar_legenda` (linhas 641 e 671)
- retry de arte em `gerar_arte_com_validacao` (linha 1015)

As funções `extrair_fatos`, `avaliar_relevancia`, `extract_editorial_hierarchy` e `validar_fatos` continuam com `model=EDITORIAL_MODEL`.

3c. Sinalizar fallbacks. Em `gerar_legenda`, no `_FALLBACK` (linha 482) adicionar chave:

```python
        "_fallback": "legenda gerada por fallback — revisar manualmente",
```

E nos dois pontos de retorno de fallback por exceção/resultado inválido (linhas 643 e 691), garantir que retornam `_FALLBACK` (já retornam). No caminho de sucesso não adicionar a chave.

Em `gerar_conteudo`, no `_FALLBACK` (linha 424) adicionar:

```python
        "_fallback": "conteúdo gerado por fallback — revisar manualmente",
```

3d. Em `resumo_telegram` (linha 753), incluir alertas de fallback — trocar o bloco `alertas`:

```python
    risco = validacao.get("risco_alucinacao", "baixo")
    alertas = []
    if post.get("_fallback"):
        alertas.append(post["_fallback"])
    if risco in ("medio", "alto"):
        for p in (validacao.get("problemas") or []):
            if p.get("trecho"):
                alertas.append(f"{p['trecho'][:60]}: {p.get('problema', '')[:80]}")
```

- [ ] **Step 4: Rodar testes**

Run: `python -m pytest tests/test_editorial.py tests/test_llm_call.py -v`
Expected: PASS em todos.

- [ ] **Step 5: Commit**

```bash
git add execution/editorial.py tests/test_editorial.py
git commit -m "feat: modelo criativo nas tarefas de escrita + fallback sinalizado como alerta"
```

---

### Task 3: `instagram_image.py` — balanced wrap, layout ancorado e preflight

**Files:**
- Modify: `execution/instagram_image.py`
- Test: `tests/test_instagram_image.py` (reescrever — hoje referencia o `6.jpg` deletado e quebra)

**Interfaces:**
- Produces: `_balanced_wrap(texto, font, max_w, draw, max_lines=3) -> list[str] | None`; `compor_titulo(title, draw, max_w=944, size_max=92, size_min=60) -> tuple[list[str] | None, ImageFont | None]`; `title_fits(title: str) -> tuple[bool, str]` (preflight usado por Task 4); `generate_ig_image(...)` sem exigência de 4 palavras e sem truncar em 6.

- [ ] **Step 1: Reescrever `tests/test_instagram_image.py` (falha primeiro)**

Substituir o conteúdo inteiro do arquivo por:

```python
"""Testa composição Pillow do instagram_image (balanced wrap + layout ancorado)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "execution"))

import pytest
from PIL import Image, ImageDraw

PROJECT_DIR = Path(__file__).parent.parent
FONT = PROJECT_DIR / "assets" / "fonts" / "Poppins-Bold.ttf"


@pytest.fixture
def cover(tmp_path):
    """Foto sintética 1600x900 — sem depender de asset externo."""
    p = tmp_path / "cover.jpg"
    img = Image.new("RGB", (1600, 900), (120, 60, 140))
    img.save(p, format="JPEG", quality=85)
    return str(p)


def test_fonte_existe():
    assert FONT.exists(), "Poppins-Bold.ttf não encontrada"


def test_title_fits_titulo_normal():
    from instagram_image import title_fits
    ok, motivo = title_fits("Americana recebe o 1º Sarau Ameriafro")
    assert ok, motivo


def test_title_fits_titulo_absurdo():
    from instagram_image import title_fits
    longo = "Inauguração extraordinariamente monumental da programação " * 4
    ok, motivo = title_fits(longo)
    assert not ok
    assert "encurte" in motivo


def test_balanced_wrap_equilibra_linhas():
    from instagram_image import _balanced_wrap, _load_font
    img = Image.new("RGBA", (1080, 1350))
    d = ImageDraw.Draw(img)
    font = _load_font(80, "black")
    linhas = _balanced_wrap("Festival de Jazz chega a Americana", font, 944, d)
    assert linhas is not None
    assert 1 <= len(linhas) <= 3
    # nenhuma linha estoura a largura máxima
    for l in linhas:
        assert d.textlength(l, font=font) <= 944


def test_generate_titulo_curto_nao_levanta_erro(cover, tmp_path):
    from instagram_image import generate_ig_image
    result = generate_ig_image(
        cover_path=cover, category="Cultura",
        title="Sarau Ameriafro",  # 2 palavras — antes levantava ValueError
        slug="t-curto", output_dir=str(tmp_path),
    )
    assert Path(result["path"]).exists()


def test_generate_titulo_longo_nao_trunca_em_6_palavras(cover, tmp_path):
    from instagram_image import generate_ig_image
    result = generate_ig_image(
        cover_path=cover, category="Música",
        title="Festival de Jazz gratuito no Parque Urbano",  # 7 palavras
        slug="t-longo", output_dir=str(tmp_path),
        subtitle="Sábado e domingo, a partir das 15h",
    )
    out = Path(result["path"])
    assert out.exists()
    img = Image.open(out)
    assert img.size == (1080, 1350)
    assert result.get("size_kb", 9999) < 1024
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `python -m pytest tests/test_instagram_image.py -v`
Expected: FAIL — `ImportError: cannot import name 'title_fits'` e `ValueError` no título de 2 palavras.

- [ ] **Step 3: Implementar em `execution/instagram_image.py`**

3a. Adicionar após `_quebrar_linhas` (linha 79):

```python
from itertools import combinations

TITLE_MAX_W  = 944
TITLE_SIZE_MAX = 92
TITLE_SIZE_MIN = 60
TITLE_MAX_LINES = 3


def _particao_equilibrada(words: list[str], n: int, font, max_w: int, draw) -> list[str] | None:
    """Divide words em n linhas contíguas minimizando a linha mais larga."""
    if n == 1:
        linha = " ".join(words)
        return [linha] if draw.textlength(linha, font=font) <= max_w else None
    if len(words) < n:
        return None
    melhor, melhor_max = None, None
    for cortes in combinations(range(1, len(words)), n - 1):
        partes, inicio = [], 0
        for c in list(cortes) + [len(words)]:
            partes.append(" ".join(words[inicio:c]))
            inicio = c
        larguras = [draw.textlength(p, font=font) for p in partes]
        if max(larguras) > max_w:
            continue
        if melhor_max is None or max(larguras) < melhor_max:
            melhor, melhor_max = partes, max(larguras)
    return melhor


def _balanced_wrap(texto: str, font, max_w: int, draw, max_lines: int = TITLE_MAX_LINES) -> list[str] | None:
    """Menor nº de linhas em que o texto cabe, com larguras equilibradas. None se não couber."""
    words = texto.split()
    if not words:
        return None
    for n in range(1, max_lines + 1):
        linhas = _particao_equilibrada(words, n, font, max_w, draw)
        if linhas is not None:
            return linhas
    return None


def compor_titulo(title: str, draw, max_w: int = TITLE_MAX_W,
                  size_max: int = TITLE_SIZE_MAX, size_min: int = TITLE_SIZE_MIN):
    """Retorna (linhas, fonte) na maior fonte que caiba, ou (None, None)."""
    for size in range(size_max, size_min - 1, -2):
        font = _load_font(size, "black")
        linhas = _balanced_wrap(title, font, max_w, draw)
        if linhas is not None:
            return linhas, font
    return None, None


def title_fits(title: str) -> tuple[bool, str]:
    """Preflight: o título renderiza em <=3 linhas com fonte >=60pt?"""
    img = Image.new("RGBA", (IG_W, IG_H))
    d = ImageDraw.Draw(img)
    linhas, _ = compor_titulo(title, d)
    if linhas is None:
        return False, (
            f"título não cabe em {TITLE_MAX_LINES} linhas com fonte mínima "
            f"{TITLE_SIZE_MIN}pt — encurte para até ~70 caracteres"
        )
    return True, ""
```

3b. Em `generate_ig_image`:
- Remover o bloco `if len(title.split()) < 4: raise ValueError(...)` (linhas 90-94).
- Substituir todo o bloco de título (linhas 171-206, da linha `words = title.split()[:6]` até o loop de desenho) e o de linha de apoio (linhas 208-214) e o do logo (216-234) por um layout ancorado de baixo para cima:

```python
    # ── Logo (calculado ANTES dos textos — âncora do layout) ─────────────────
    logo_img, logo_pos = None, None
    logo_top = H - 58 - 90  # fallback se logo falhar: reserva ~90px
    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
        pixels = list(logo.getdata())
        logo.putdata([
            (r, g, b, 0) if r > 230 and g > 230 and b > 230 else (r, g, b, a)
            for r, g, b, a in pixels
        ])
        bbox = logo.getbbox()
        if bbox:
            logo = logo.crop(bbox)
        LW = 240
        LH = int(logo.height * LW / logo.width)
        logo_img = logo.resize((LW, LH), Image.LANCZOS)
        logo_pos = ((W - LW) // 2, H - LH - 58)
        logo_top = logo_pos[1]
    except Exception as e:
        print(f"[instagram_image] aviso: logo não colado — {e}", file=sys.stderr)

    # ── Título: balanced wrap com autosize; fallback duro se não couber ──────
    linhas, fonte_ok = compor_titulo(title, d)
    if linhas is None:
        # Último recurso determinístico: fonte mínima, quebra gulosa, 3 linhas + "…"
        fonte_ok = _load_font(TITLE_SIZE_MIN, "black")
        linhas = _quebrar_linhas(title, fonte_ok, TITLE_MAX_W, d)[:TITLE_MAX_LINES]
        if linhas:
            linhas[-1] = linhas[-1].rstrip() + "…"
        print(f"[instagram_image] aviso: título não coube — truncado com reticências.",
              file=sys.stderr)

    # ── Linha de apoio (medida antes de posicionar o bloco) ──────────────────
    fa = _load_font(38, "regular")
    sub_linhas = _quebrar_linhas(subtitle, fa, 940, d) if subtitle else []

    # ── Alturas do bloco de texto (badge + título + apoio) ───────────────────
    ft = _load_font(28, "bold")
    cat_up = category.upper()
    bb = d.textbbox((0, 0), cat_up, font=ft)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    PW, PH = 32, 14  # padding interno do badge
    badge_h = th + PH * 2
    titulo_h = int(fonte_ok.size * 1.08) * len(linhas)
    apoio_h = (32 + int(fa.size * 1.35) * len(sub_linhas)) if sub_linhas else 0
    bloco_h = badge_h + 22 + titulo_h + apoio_h

    # ── Posiciona o bloco ancorado acima do logo, com respiro de 40px ────────
    y0 = logo_top - 40 - bloco_h

    # Badge
    TX = 68
    rect = [TX, y0, TX + tw + PW * 2, y0 + badge_h]
    d.rounded_rectangle(rect, radius=8, fill=(221, 230, 0))
    d.text((TX + PW, y0 + PH), cat_up, font=ft, fill=(0, 0, 0))

    # Título
    ty = rect[3] + 22
    for linha in linhas:
        d.text((68, ty), linha, font=fonte_ok, fill=(255, 255, 255))
        ty += int(fonte_ok.size * 1.08)

    # Linha de apoio
    if sub_linhas:
        ay = ty + 32
        for linha in sub_linhas:
            d.text((68, ay), linha, font=fa, fill=(255, 255, 255))
            ay += int(fa.size * 1.35)

    # Logo por último (por cima do degradê)
    if logo_img is not None:
        canvas.alpha_composite(logo_img, logo_pos)
```

Atenção: esse bloco substitui também o antigo "Tag de categoria" (linhas 159-169) — o badge agora é desenhado dentro do layout ancorado. O `import sys` já existe no topo; remover o `__import__("sys")` do except antigo.

- [ ] **Step 4: Rodar testes**

Run: `python -m pytest tests/test_instagram_image.py -v`
Expected: 6 PASS

- [ ] **Step 5: Verificação visual**

Run: `python execution/instagram_image.py --cover "Oficina Efeitos especiais Americana SP.jpg" --slug preview --title "Oficina de efeitos especiais em Americana" --category "Cultura" --art-subtitle "Inscrições abertas, vagas limitadas" --output-dir .tmp`
Expected: JSON com path `.tmp/preview_ig.webp`. Abrir o arquivo e conferir: título em 2-3 linhas equilibradas, badge acima, bloco de texto sem colidir com o logo.

- [ ] **Step 6: Commit**

```bash
git add execution/instagram_image.py tests/test_instagram_image.py
git commit -m "feat: arte IG com balanced wrap, layout ancorado e title_fits — fim do corte em 6 palavras"
```

---

### Task 4: preflight do título substitui contagem de palavras

**Files:**
- Modify: `execution/editorial.py` (funções `validar_arte`, `_erros_criticos_arte`, prompt de `gerar_conteudo`)
- Modify: `execution/run_releases.py:355-364` (remover gambiarra de enchimento)
- Test: `tests/test_editorial.py` (adicionar casos)

**Interfaces:**
- Consumes: `title_fits(title) -> tuple[bool, str]` de Task 3.
- Produces: `validar_arte` e `_erros_criticos_arte` validam por renderização, não por contagem. `run_releases` passa `texto_arte.titulo_principal` direto ao `instagram_image.py` sem enchimento.

- [ ] **Step 1: Adicionar testes em `tests/test_editorial.py`**

```python
def test_erros_criticos_arte_usa_preflight_visual():
    import editorial
    # 7 palavras curtas: cabe visualmente — NÃO pode mais ser erro
    arte = {"titulo_principal": "Jazz no parque com shows ao vivo",
            "linha_apoio": "Sábado, 15h", "badge": "MÚSICA"}
    erros = editorial._erros_criticos_arte(arte, {"gratuito": True})
    assert not any("palavra" in e or "coube" in e for e in erros), erros


def test_erros_criticos_arte_rejeita_titulo_que_nao_cabe():
    import editorial
    arte = {"titulo_principal": "Inauguração extraordinariamente monumental " * 4,
            "linha_apoio": "x", "badge": "CULTURA"}
    erros = editorial._erros_criticos_arte(arte, {"gratuito": True})
    assert any("não cabe" in e for e in erros), erros


def test_validar_arte_titulo_curto_permanece():
    import editorial
    arte = {"titulo_principal": "Sarau Ameriafro", "linha_apoio": "Dia 16, na Estação Cultura",
            "badge": "CULTURA"}
    corrigida, alertas = editorial.validar_arte(arte, {"gratuito": True})
    assert corrigida["titulo_principal"] == "Sarau Ameriafro"
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `python -m pytest tests/test_editorial.py -v`
Expected: FAIL no teste de 7 palavras (regra atual rejeita >6 palavras).

- [ ] **Step 3: Implementar**

3a. `execution/editorial.py` — topo, junto ao `import llm_call as _llm`:

```python
import instagram_image as _ig
```

3b. Em `validar_arte` (linha 823), substituir o bloco "2. Máx 6 palavras" (linhas 839-843) por:

```python
    # 2. Preflight visual: título deve renderizar em <=3 linhas com fonte >=60pt
    cabe, motivo = _ig.title_fits(titulo)
    if not cabe:
        alertas.append(f"titulo_principal {motivo} — aplicando fallback")
        titulo = _fallback_titulo_arte(fatos)
```

3c. Em `_erros_criticos_arte` (linha 899), adicionar dentro do `else` do título (após a checagem de hashtag, linha 918):

```python
        cabe, motivo = _ig.title_fits(titulo)
        if not cabe:
            erros.append(f"titulo_principal não cabe na arte: {motivo}")
```

3d. No prompt de `gerar_conteudo` (linhas 403 e 411-414), trocar as regras de contagem por regras de comprimento:

```
  - titulo_principal: manchete visual de 15 a 70 caracteres — curta e direta, estilo post social
  - titulo_principal SEM ponto final, SEM hashtags (#)
```

E substituir os exemplos CERTO/ERRADO (mantendo o espírito):

```
    CERTO: "Palhaços na praça hoje", "Sarau Ameriafro em Americana", "Festival de Jazz no Parque Urbano"
    ERRADO (comprido demais, +70 chars): "Espetáculo gratuito de palhaços acontece hoje na praça central da cidade"
    ERRADO (estilo release): "Projeto leva magia da leitura para crianças"
```

3e. `execution/run_releases.py` — remover as linhas 358-364 (bloco "Garante mínimo de 4 palavras"), deixando:

```python
        art_title = post.get("texto_arte", {}).get("titulo_principal", "") or titulo
        art_subtitle = post.get("texto_arte", {}).get("linha_apoio", "")
```

- [ ] **Step 4: Rodar testes**

Run: `python -m pytest tests/ -v`
Expected: PASS em todos.

- [ ] **Step 5: Commit**

```bash
git add execution/editorial.py execution/run_releases.py tests/test_editorial.py
git commit -m "feat: validação de título da arte por preflight visual — fim da contagem de palavras"
```

---

### Task 5: `wp_publish.py` — comandos `find` e `set-featured`

**Files:**
- Modify: `execution/wp_publish.py`
- Test: `tests/test_wp_publish.py` (criar, com requests mockado)

**Interfaces:**
- Produces (CLI e função):
  - `find_post(slug: str = "", search: str = "") -> dict` → `{"exists": bool, "post_id": int | None, "status": str}` — consulta `/wp-json/wp/v2/posts?status=publish,draft,pending,future` por slug exato ou busca textual.
  - `set_featured(post_id: int, image_path: str) -> dict` → `{"post_id": int, "media_id": int, "url": str}` — sobe a imagem e define como destacada.
  - CLI: `wp_publish.py find --slug X | --search "Y"` e `wp_publish.py set-featured --post-id N --image-path P`.

- [ ] **Step 1: Escrever teste que falha**

Criar `tests/test_wp_publish.py`:

```python
"""Testa find_post e set_featured com API mockada."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "execution"))


def _setup_env(monkeypatch):
    monkeypatch.setenv("WP_URL", "https://exemplo.com")
    monkeypatch.setenv("WP_USER", "u")
    monkeypatch.setenv("WP_APP_PASSWORD", "p")


class FakeResp:
    def __init__(self, payload):
        self._payload = payload
        self.ok = True
        self.status_code = 200

    def json(self):
        return self._payload


def test_find_post_por_slug_existente(monkeypatch):
    _setup_env(monkeypatch)
    import wp_publish

    def fake_get(url, params=None, auth=None):
        assert params["slug"] == "meu-post"
        return FakeResp([{"id": 42, "status": "draft"}])

    monkeypatch.setattr(wp_publish.requests, "get", fake_get)
    result = wp_publish.find_post(slug="meu-post")
    assert result == {"exists": True, "post_id": 42, "status": "draft"}


def test_find_post_inexistente(monkeypatch):
    _setup_env(monkeypatch)
    import wp_publish

    monkeypatch.setattr(wp_publish.requests, "get",
                        lambda url, params=None, auth=None: FakeResp([]))
    result = wp_publish.find_post(slug="nao-existe")
    assert result == {"exists": False, "post_id": None, "status": ""}


def test_set_featured(monkeypatch, tmp_path):
    _setup_env(monkeypatch)
    import wp_publish

    img = tmp_path / "a.jpg"
    img.write_bytes(b"fake")

    monkeypatch.setattr(wp_publish, "upload_image",
                        lambda p, title="": {"media_id": 7, "url": "https://exemplo.com/a.jpg"})

    captured = {}

    def fake_post(url, json=None, auth=None, headers=None, data=None):
        captured["url"] = url
        captured["json"] = json
        return FakeResp({"id": 42, "featured_media": 7})

    monkeypatch.setattr(wp_publish.requests, "post", fake_post)
    result = wp_publish.set_featured(42, str(img))
    assert captured["json"] == {"featured_media": 7}
    assert result == {"post_id": 42, "media_id": 7, "url": "https://exemplo.com/a.jpg"}
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `python -m pytest tests/test_wp_publish.py -v`
Expected: FAIL — `AttributeError: no attribute 'find_post'`.

- [ ] **Step 3: Implementar em `execution/wp_publish.py`**

Adicionar após `trash_post` (linha 188):

```python
def find_post(slug: str = "", search: str = "") -> dict:
    """Verifica se já existe post (qualquer status) com este slug ou busca textual."""
    wp_url, auth = get_config()
    params: dict = {"status": "publish,draft,pending,future", "per_page": 5}
    if slug:
        params["slug"] = slug
    elif search:
        params["search"] = search
    else:
        print("Erro: informe --slug ou --search", file=sys.stderr)
        sys.exit(1)

    resp = requests.get(f"{wp_url}/wp-json/wp/v2/posts", params=params, auth=auth)
    if not resp.ok:
        # Em erro de API, assume que não existe (não bloqueia o pipeline)
        print(f"Aviso: find falhou ({resp.status_code}) — assumindo inexistente", file=sys.stderr)
        return {"exists": False, "post_id": None, "status": ""}

    posts = resp.json()
    if posts:
        return {"exists": True, "post_id": posts[0]["id"], "status": posts[0].get("status", "")}
    return {"exists": False, "post_id": None, "status": ""}


def set_featured(post_id: int, image_path: str) -> dict:
    """Sobe imagem e define como destacada de um post existente."""
    wp_url, auth = get_config()
    up = upload_image(image_path)
    resp = requests.post(
        f"{wp_url}/wp-json/wp/v2/posts/{post_id}",
        json={"featured_media": up["media_id"]},
        auth=auth,
    )
    _check_response(resp)
    return {"post_id": post_id, "media_id": up["media_id"], "url": up.get("url", "")}
```

No `main()`, adicionar os subparsers (após o bloco `upload-image`, linha 214):

```python
    p_find = subparsers.add_parser("find", help="Verifica se post existe por slug ou busca")
    p_find.add_argument("--slug", default="")
    p_find.add_argument("--search", default="")

    p_sf = subparsers.add_parser("set-featured", help="Define imagem destacada de post existente")
    p_sf.add_argument("--post-id", type=int, required=True)
    p_sf.add_argument("--image-path", required=True)
```

E no dispatch:

```python
    elif args.command == "find":
        result = find_post(slug=args.slug, search=args.search)
    elif args.command == "set-featured":
        result = set_featured(args.post_id, args.image_path)
```

- [ ] **Step 4: Rodar testes**

Run: `python -m pytest tests/test_wp_publish.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add execution/wp_publish.py tests/test_wp_publish.py
git commit -m "feat: wp_publish find (dedup) e set-featured (gate de imagem)"
```

---

### Task 6: vision tri-state + fim do placeholder + flag `validated`

**Files:**
- Modify: `execution/image_generate.py`
- Modify: `execution/run_releases.py:121-187` (`_imagem_relevante`)
- Test: `tests/test_image_generate.py` (criar)

**Interfaces:**
- Produces:
  - `_validate_image(image_path, titulo) -> str` retorna `"yes"`, `"no"` ou `"unavailable"` (em vez de bool). Sem `GEMINI_API_KEY` → `"unavailable"`.
  - `generate_image(query, slug, output_dir, titulo) -> dict` → `{"path": str, "source": str, "credit": str, "validated": bool}`. Quando a vision está indisponível, retorna o melhor candidato com `"validated": False` (vira *sugestão*, não capa). Se nenhuma fonte retornou nada: `{"path": "", "source": "none", "credit": "", "validated": False}`. **Nunca** gera placeholder e **nunca** chama `sys.exit(1)`.
  - `run_releases._imagem_relevante(image_path, titulo) -> str` (`"yes"`/`"no"`/`"unavailable"`).

- [ ] **Step 1: Escrever teste que falha**

Criar `tests/test_image_generate.py`:

```python
"""Testa tri-state da vision e fim do placeholder em image_generate."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "execution"))


def test_validate_sem_chave_retorna_unavailable(monkeypatch, tmp_path):
    import image_generate
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    img = tmp_path / "x.jpg"
    img.write_bytes(b"fake")
    assert image_generate._validate_image(str(img), "titulo") == "unavailable"


def test_generate_sem_fontes_retorna_vazio_sem_placeholder(monkeypatch):
    import image_generate
    monkeypatch.setattr(image_generate, "_try_unsplash", lambda *a, **k: None)
    monkeypatch.setattr(image_generate, "_try_pexels", lambda *a, **k: None)
    monkeypatch.setattr(image_generate, "_try_gemini", lambda *a, **k: None)
    monkeypatch.setattr(image_generate, "_try_openai", lambda *a, **k: None)
    result = image_generate.generate_image("q", "slug", ".tmp", "titulo")
    assert result == {"path": "", "source": "none", "credit": "", "validated": False}
    assert not hasattr(image_generate, "_try_pil_placeholder"), "placeholder deve ser removido"
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `python -m pytest tests/test_image_generate.py -v`
Expected: FAIL — `_validate_image` retorna `True` (bool) e `_try_pil_placeholder` existe.

- [ ] **Step 3: Implementar**

3a. `execution/image_generate.py`, `_validate_image` (linha 49):
- Docstring nova: retorna `"yes" | "no" | "unavailable"`.
- Sem chave (linha 56-57): `return "unavailable"`.
- Resultado da vision (linhas 122-127):

```python
        words = _re.findall(r"\b(yes|no)\b", response.text.strip().lower())
        veredito = words[-1] if words else "no"
        if veredito == "no":
            print(f"[image_generate] Imagem rejeitada pela vision: {image_path}", file=sys.stderr)
        return veredito
```

- No except (linhas 129-142): caso 503 → `return "unavailable"` (não mais `True`); outros erros → `return "no"`.

3b. Nos loops de candidatos de `_try_unsplash` (linha 204) e `_try_pexels` (linha 273), substituir o check por:

```python
            veredito = _validate_image(raw_path, titulo) if titulo else "yes"
            if veredito == "no":
                print(f"...candidato {idx+1} rejeitado, tentando próximo.", file=sys.stderr)
                continue
```

E incluir no dict de retorno de ambos: `"validated": veredito == "yes"` (quando `"unavailable"`, o candidato retorna como sugestão não-validada). `_try_gemini` e `_try_openai` retornam `"validated": True` (imagem gerada sob controle, sem texto).

3c. Remover a função `_try_pil_placeholder` inteira (linhas 406-420) e o bloco final de `generate_image` (linhas 435-441), substituindo por:

```python
    print("Aviso: nenhuma fonte de imagem retornou candidato.", file=sys.stderr)
    return {"path": "", "source": "none", "credit": "", "validated": False}
```

3d. `execution/run_releases.py`, `_imagem_relevante` (linha 121): mesma conversão tri-state — sem chave → `"unavailable"`; 503 → `"unavailable"`; erro → `"no"`; senão `words[-1]`. Atualizar docstring.

- [ ] **Step 4: Rodar testes**

Run: `python -m pytest tests/test_image_generate.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add execution/image_generate.py execution/run_releases.py tests/test_image_generate.py
git commit -m "feat: vision tri-state (yes/no/unavailable) e eliminação do placeholder cinza"
```

---

### Task 7: `telegram_notify.py` — card de imagem pendente

**Files:**
- Modify: `execution/telegram_notify.py`
- Test: `tests/test_telegram_notify.py` (criar)

**Interfaces:**
- Produces:
  - `cmd_send_image_pending(data: dict) -> dict` — envia card "⚠️ Sem imagem adequada" com a sugestão (se houver) e botões `[✔️ Usar sugestão]` (`callback_data=f"usethis:{post_id}"`) e `[📷 Vou enviar foto]` (`callback_data=f"sendphoto:{post_id}"`). CLI: `telegram_notify.py send-image-pending --data '<json>'`.
  - Estado: `.tmp/pending_images.json` com schema `{"cards": {"<msg_id>": {...entry...}}, "awaiting": null | {"post_id": int, "msg_id": str}}`.
  - Entry (produzido por Task 9, consumido por Task 8): `{"post_id", "slug", "titulo", "category_name", "art_title", "art_subtitle", "legenda_curta", "legenda_longa", "edit_url", "summary", "card_meta", "suggestion_path", "suggestion_credit"}`.
  - Helpers exportados: `_load_pending_images() -> dict`, `_save_pending_images(data) -> None` (com defaults `{"cards": {}, "awaiting": None}`).

- [ ] **Step 1: Escrever teste que falha**

Criar `tests/test_telegram_notify.py`:

```python
"""Testa card de imagem pendente e estado pending_images."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "execution"))


def test_send_image_pending_registra_estado(monkeypatch, tmp_path):
    import telegram_notify as tn

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    monkeypatch.setattr(tn, "PENDING_IMAGES_FILE", tmp_path / "pending_images.json")

    captured = {}

    def fake_api(method, poll_timeout=0, **kwargs):
        captured["method"] = method
        captured["kwargs"] = kwargs
        return {"ok": True, "result": {"message_id": 99}}

    monkeypatch.setattr(tn, "_api", fake_api)

    data = {
        "post_id": 42, "slug": "meu-post", "titulo": "Título",
        "category_name": "Cultura", "art_title": "Título arte",
        "art_subtitle": "apoio", "legenda_curta": "leg", "legenda_longa": "leg2",
        "edit_url": "https://x/edit", "summary": "resumo", "card_meta": {},
        "suggestion_path": "", "suggestion_credit": "",
    }
    result = tn.cmd_send_image_pending(data)
    assert result["ok"] is True

    state = json.loads((tmp_path / "pending_images.json").read_text(encoding="utf-8"))
    assert state["cards"]["99"]["post_id"] == 42
    assert state["awaiting"] is None

    # botões corretos no teclado
    kb = captured["kwargs"]["json"]["reply_markup"]["inline_keyboard"]
    datas = [b["callback_data"] for row in kb for b in row]
    assert "sendphoto:42" in datas
    assert "usethis:42" not in datas  # sem sugestão, botão "usar" não aparece
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `python -m pytest tests/test_telegram_notify.py -v`
Expected: FAIL — `cmd_send_image_pending` não existe.

- [ ] **Step 3: Implementar em `execution/telegram_notify.py`**

Adicionar após `_save_pending_pautas` (linha 283):

```python
PENDING_IMAGES_FILE = Path(".tmp/pending_images.json")


def _load_pending_images() -> dict:
    if PENDING_IMAGES_FILE.exists():
        data = json.loads(PENDING_IMAGES_FILE.read_text(encoding="utf-8"))
    else:
        data = {}
    data.setdefault("cards", {})
    data.setdefault("awaiting", None)
    return data


def _save_pending_images(data: dict) -> None:
    PENDING_IMAGES_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_IMAGES_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_send_image_pending(data: dict) -> dict:
    """
    Card de imagem pendente: rascunho criado sem imagem destacada.
    Botões: [Usar sugestão] (se houver) e [Vou enviar foto].
    """
    post_id = data["post_id"]
    titulo = data.get("titulo", "")
    edit_url = data.get("edit_url", "")
    suggestion_path = data.get("suggestion_path", "")
    suggestion_credit = data.get("suggestion_credit", "")

    texto = (
        f"⚠️ *Sem imagem adequada*\n\n"
        f"📰 {_escape(titulo)}\n\n"
        f"O rascunho foi criado sem imagem destacada\\. "
        f"Escolha uma opção abaixo ou edite direto no WP\\.\n\n"
        f"[Editar rascunho]({edit_url})"
    )

    row = []
    if suggestion_path and Path(suggestion_path).exists():
        row.append({"text": "✔️ Usar sugestão", "callback_data": f"usethis:{post_id}"})
    row.append({"text": "📷 Vou enviar foto", "callback_data": f"sendphoto:{post_id}"})
    keyboard = {"inline_keyboard": [row]}

    if suggestion_path and Path(suggestion_path).exists():
        caption = texto
        if suggestion_credit:
            caption += f"\n\n_Sugestão: {_escape(suggestion_credit)}_"
        if len(caption) > 1024:
            caption = caption[:1021] + "…"
        with Path(suggestion_path).open("rb") as f:
            result = _api("sendPhoto", data={
                "chat_id": _chat_id(), "caption": caption,
                "parse_mode": "MarkdownV2",
                "reply_markup": json.dumps(keyboard),
            }, files={"photo": f})
    else:
        result = _api("sendMessage", json={
            "chat_id": _chat_id(), "text": texto,
            "parse_mode": "MarkdownV2", "reply_markup": keyboard,
        })

    if result.get("ok"):
        msg_id = str(result["result"]["message_id"])
        state = _load_pending_images()
        state["cards"][msg_id] = data
        _save_pending_images(state)
        print(f"Card de imagem pendente enviado. message_id={msg_id}", file=sys.stderr)
        return {"ok": True, "message_id": int(msg_id)}
    return {"ok": False, "error": result}
```

No `main()`, adicionar subparser e dispatch:

```python
    p_sip = subparsers.add_parser("send-image-pending", help="Card de rascunho sem imagem")
    p_sip.add_argument("--data", required=True, help="JSON com entry de imagem pendente")
```

```python
    elif args.command == "send-image-pending":
        result = cmd_send_image_pending(json.loads(args.data))
```

- [ ] **Step 4: Rodar testes**

Run: `python -m pytest tests/test_telegram_notify.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add execution/telegram_notify.py tests/test_telegram_notify.py
git commit -m "feat: card Telegram de imagem pendente com [Usar sugestão]/[Vou enviar foto]"
```

---

### Task 8: `telegram_bot.py` — callbacks de imagem + recebimento de foto

**Files:**
- Modify: `execution/telegram_bot.py`

**Interfaces:**
- Consumes: `_load_pending_images`/`_save_pending_images`/schema de entry (Task 7); `wp_publish.py set-featured` (Task 5); `image_process.py --input --slug --output-dir` (existente); `instagram_image.py --cover --slug --title --category --art-title --art-subtitle` (existente); `wp_publish.py upload-image`; `telegram_notify.py send-release` (existente).
- Produces: fluxo completo — clicar `usethis:` ou responder foto após `sendphoto:` resulta em post com imagem destacada + arte IG + card de aprovação normal.

- [ ] **Step 1: Implementar handlers em `execution/telegram_bot.py`**

1a. No `getUpdates` (linha 229), incluir mensagens:

```python
                    "allowed_updates": ["callback_query", "message"],
```

1b. Adicionar funções após `_handle_approval` (linha 212):

```python
def _completar_com_imagem(entry: dict, raw_image_path: str) -> None:
    """
    Fecha uma pendência de imagem: processa a foto, define destacada no WP,
    gera arte IG e envia o card de aprovação completo.
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    slug = entry["slug"]
    post_id = entry["post_id"]
    output_dir = str(PROJECT_DIR / ".tmp")

    def _run_json_local(args: list[str]) -> dict | None:
        result = subprocess.run(["python3"] + args, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", cwd=str(PROJECT_DIR))
        if result.returncode != 0:
            print(f"[bot] Erro em {Path(args[0]).name}: {result.stderr[:300]}", file=sys.stderr)
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return None

    # 1. Processa para capa 1920x1080 WebP
    proc = _run_json_local([str(SCRIPT_DIR / "image_process.py"),
                            "--input", raw_image_path, "--slug", slug,
                            "--output-dir", output_dir])
    if not proc or not proc.get("path"):
        _send_text(f"❌ Falha ao processar a imagem do post #{post_id}. Tente outra foto.")
        return
    cover_path = proc["path"]

    # 2. Define imagem destacada no WP
    _run_json_local([str(SCRIPT_DIR / "wp_publish.py"), "set-featured",
                     "--post-id", str(post_id), "--image-path", cover_path])

    # 3. Gera arte IG e sobe para o WP Media
    ig_path = ""
    ig_result = _run_json_local([
        str(SCRIPT_DIR / "instagram_image.py"),
        "--cover", cover_path, "--slug", slug,
        "--title", entry.get("titulo", ""),
        "--category", entry.get("category_name", "Eventos"),
        "--art-title", entry.get("art_title", ""),
        "--art-subtitle", entry.get("art_subtitle", ""),
        "--output-dir", output_dir,
    ])
    if ig_result:
        ig_path = ig_result.get("path", "")
        if ig_path:
            _run_json_local([str(SCRIPT_DIR / "wp_publish.py"), "upload-image",
                             "--image-path", ig_path,
                             "--title", f"{entry.get('titulo', '')} — Instagram"])

    # 4. Envia o card de aprovação completo
    notify_args = [str(SCRIPT_DIR / "telegram_notify.py"), "send-release",
                   "--post-id", str(post_id),
                   "--title", entry.get("titulo", ""),
                   "--summary", entry.get("summary", ""),
                   "--edit-url", entry.get("edit_url", ""),
                   "--cover", cover_path,
                   "--sheets-row-id", "0"]
    if entry.get("card_meta"):
        notify_args += ["--card-meta", json.dumps(entry["card_meta"], ensure_ascii=False)]
    if ig_path:
        notify_args += ["--ig-image", ig_path, "--ig-caption", entry.get("legenda_curta", "")]
    subprocess.run(["python3"] + notify_args, cwd=str(PROJECT_DIR))
    print(f"[bot] Pendência de imagem do post #{post_id} resolvida.", file=sys.stderr)


def _handle_image_callback(action: str, post_id_str: str, cb_id: str, msg_id: str) -> None:
    """Callbacks usethis:<post_id> e sendphoto:<post_id>."""
    sys.path.insert(0, str(SCRIPT_DIR))
    from telegram_notify import _load_pending_images, _save_pending_images

    state = _load_pending_images()
    entry = state["cards"].get(msg_id)
    if not entry or str(entry.get("post_id")) != post_id_str:
        _api("answerCallbackQuery", json={"callback_query_id": cb_id,
                                          "text": "Este card já foi processado."})
        return

    if action == "usethis":
        _api("answerCallbackQuery", json={"callback_query_id": cb_id,
                                          "text": "✔️ Usando a sugestão..."})
        _api("editMessageReplyMarkup", json={
            "chat_id": _chat_id(), "message_id": int(msg_id),
            "reply_markup": json.dumps({"inline_keyboard": []})})
        state["cards"].pop(msg_id, None)
        _save_pending_images(state)
        _completar_com_imagem(entry, entry.get("suggestion_path", ""))

    elif action == "sendphoto":
        _api("answerCallbackQuery", json={"callback_query_id": cb_id,
                                          "text": "📷 Manda a foto aqui no chat."})
        state["awaiting"] = {"post_id": entry["post_id"], "msg_id": msg_id}
        _save_pending_images(state)
        _send_text(f"📷 Aguardando foto para o post #{entry['post_id']} — envie como imagem aqui no chat.")


def _handle_photo_message(message: dict) -> None:
    """Foto recebida no chat: se há pendência aguardando, resolve com ela."""
    sys.path.insert(0, str(SCRIPT_DIR))
    from telegram_notify import _load_pending_images, _save_pending_images

    state = _load_pending_images()
    awaiting = state.get("awaiting")
    if not awaiting:
        return  # foto sem pendência ativa — ignora

    photos = message.get("photo", [])
    if not photos:
        return
    file_id = photos[-1]["file_id"]  # maior resolução

    # Baixa o arquivo do Telegram
    info = _api("getFile", json={"file_id": file_id})
    file_path = info.get("result", {}).get("file_path", "")
    if not file_path:
        _send_text("❌ Não consegui baixar a foto. Tente novamente.")
        return
    url = f"https://api.telegram.org/file/bot{_token()}/{file_path}"
    resp = requests.get(url, timeout=60)

    msg_id = awaiting["msg_id"]
    entry = state["cards"].get(msg_id)
    if not entry:
        state["awaiting"] = None
        _save_pending_images(state)
        return

    raw_path = PROJECT_DIR / ".tmp" / f"{entry['slug']}_telegram.jpg"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(resp.content)

    # Limpa a pendência antes de completar (evita reuso duplo)
    state["cards"].pop(msg_id, None)
    state["awaiting"] = None
    _save_pending_images(state)
    _api("editMessageReplyMarkup", json={
        "chat_id": _chat_id(), "message_id": int(msg_id),
        "reply_markup": json.dumps({"inline_keyboard": []})})

    _send_text(f"✅ Foto recebida! Processando o post #{entry['post_id']}...")
    _completar_com_imagem(entry, str(raw_path))
```

1c. No loop principal, após o bloco `cb = update.get("callback_query")` (linha 260), tratar mensagens — inserir antes do `if not cb: continue`:

```python
                msg = update.get("message")
                if msg and msg.get("photo"):
                    _handle_photo_message(msg)
                    continue

                cb = update.get("callback_query")
                if not cb:
                    continue
```

1d. No dispatch de callbacks (linha 271), adicionar antes do bloco `else`:

```python
                elif data_str.startswith(("usethis:", "sendphoto:")):
                    action, pid = data_str.split(":", 1)
                    _handle_image_callback(action, pid, cb_id, msg_id)
```

- [ ] **Step 2: Verificação estática**

Run: `python -m py_compile execution/telegram_bot.py && python -m pytest tests/ -v`
Expected: compila sem erro; testes existentes PASS. (O fluxo completo é validado manualmente na Task 12 — exige Telegram real.)

- [ ] **Step 3: Commit**

```bash
git add execution/telegram_bot.py
git commit -m "feat: bot Telegram resolve pendência de imagem — usar sugestão ou receber foto no chat"
```

---

### Task 9: `run_releases.py` — integração do gate de imagem

**Files:**
- Modify: `execution/run_releases.py` (`_pipeline_imagem` e `processar_email`)

**Interfaces:**
- Consumes: `_imagem_relevante` tri-state (Task 6), `generate_image` com `validated` (Task 6), `telegram_notify.py send-image-pending` (Task 7).
- Produces: `_pipeline_imagem(email, slug, titulo, fatos) -> dict` com novo retorno `{"cover_path": str, "credit": str, "suggestion_path": str, "suggestion_credit": str}` — `cover_path` vazio significa "sem imagem aprovada".

- [ ] **Step 1: Alterar `_pipeline_imagem` (linhas 190-259)**

Substituir a assinatura e o corpo:

```python
def _pipeline_imagem(email: dict, slug: str, titulo: str = "", fatos: dict | None = None) -> dict:
    """
    Seleciona imagem de capa. Prioridade: fotos do email > banco de imagens.
    Retorna dict:
      cover_path        — capa aprovada ("" se nenhuma)
      credit            — crédito da capa
      suggestion_path   — melhor candidata NÃO validada (para o card de pendência)
      suggestion_credit — crédito da sugestão
    """
    if fatos is None:
        fatos = {}
    vazio = {"cover_path": "", "credit": "", "suggestion_path": "", "suggestion_credit": ""}
    attachments = email.get("attachments", [])
    sugestao_path, sugestao_credit = "", ""

    if attachments:
        scored = []
        for att in attachments:
            r = _run_json([str(SCRIPT_DIR / "image_select.py"), "--images", att])
            if r and r.get("score", -1) >= 0:
                scored.append(r)
        scored.sort(key=lambda x: x.get("score", 0), reverse=True)
        print(f"[run_releases] {len(scored)} foto(s) do email para avaliar.", file=sys.stderr)

        for candidate in scored:
            cpath = candidate.get("path")
            if not cpath or not _imagem_adequada_para_arte(cpath):
                continue
            veredito = _imagem_relevante(cpath, titulo) if titulo else "yes"
            if veredito == "no":
                print(f"[run_releases] Foto rejeitada (vision): {Path(cpath).name}", file=sys.stderr)
                continue
            proc_result = _run_json([
                str(SCRIPT_DIR / "image_process.py"),
                "--input", cpath, "--slug", slug, "--output-dir", OUTPUT_DIR,
            ])
            if not proc_result or not proc_result.get("path"):
                continue
            if veredito == "unavailable":
                # Vision fora do ar: foto do email vira sugestão, não capa automática
                if not sugestao_path:
                    sugestao_path, sugestao_credit = proc_result["path"], ""
                    print(f"[run_releases] Vision indisponível — foto vira sugestão.", file=sys.stderr)
                continue
            print(f"[run_releases] Usando foto do email: {Path(cpath).name}", file=sys.stderr)
            return {**vazio, "cover_path": proc_result["path"]}

        print(f"[run_releases] Nenhuma foto do email aprovada.", file=sys.stderr)

    # Banco de imagens (Unsplash/Pexels/IA)
    from editorial import query_from_fatos
    img_query = query_from_fatos(fatos, titulo)
    print(f"[run_releases] Buscando em bancos | query='{img_query}'...", file=sys.stderr)
    gen_result = _run_json([
        str(SCRIPT_DIR / "image_generate.py"),
        "--query", img_query, "--slug", slug,
        "--titulo", titulo, "--output-dir", OUTPUT_DIR,
    ])
    if gen_result and gen_result.get("path"):
        if gen_result.get("validated"):
            return {**vazio,
                    "cover_path": gen_result["path"],
                    "credit": gen_result.get("credit", "")}
        # Candidato não validado — vira sugestão (se ainda não temos uma do email)
        if not sugestao_path:
            sugestao_path = gen_result["path"]
            sugestao_credit = gen_result.get("credit", "")

    return {**vazio, "suggestion_path": sugestao_path, "suggestion_credit": sugestao_credit}
```

- [ ] **Step 2: Adaptar `processar_email` (linhas 343-407 e 473-489)**

2a. Trocar a chamada (linha 344):

```python
    img = _pipeline_imagem(email, slug, titulo, fatos=fatos)
    cover_path = img["cover_path"]
    foto_credit_gerada = img["credit"]
```

2b. Manter geração de arte/legenda/validação como está (arte só roda com `cover_path` — já é condicional).

2c. Após criar o rascunho no WP e antes da notificação (linha 473), bifurcar a notificação:

```python
    if cover_path:
        # Fluxo normal: card completo de aprovação
        notify_args = [
            str(SCRIPT_DIR / "telegram_notify.py"), "send-release",
            "--post-id", str(post_id),
            "--title", titulo,
            "--summary", post.get("resumo_telegram", html[:300].replace("<", "").replace(">", "")[:200]),
            "--edit-url", edit_url,
            "--cover", cover_path,
            "--sheets-row-id", "0",
            "--card-meta", json.dumps(card_meta, ensure_ascii=False),
        ]
        if ig_path:
            notify_args += ["--ig-image", ig_path, "--ig-caption", legenda_curta]
        notify_result = _run(notify_args)
    else:
        # Sem imagem aprovada: card de pendência — humano decide a imagem
        pending_entry = {
            "post_id": post_id,
            "slug": slug,
            "titulo": titulo,
            "category_name": CATEGORY_NAMES.get(wp_category_id, "Eventos"),
            "art_title": post.get("texto_arte", {}).get("titulo_principal", "") or titulo,
            "art_subtitle": post.get("texto_arte", {}).get("linha_apoio", ""),
            "legenda_curta": legenda_curta,
            "legenda_longa": legenda_longa,
            "edit_url": edit_url,
            "summary": post.get("resumo_telegram", ""),
            "card_meta": card_meta,
            "suggestion_path": img["suggestion_path"],
            "suggestion_credit": img["suggestion_credit"],
        }
        notify_result = _run([
            str(SCRIPT_DIR / "telegram_notify.py"), "send-image-pending",
            "--data", json.dumps(pending_entry, ensure_ascii=False),
        ])
```

2d. A passagem de `--sheets-row-id` usa `"0"` fixo (o Sheets sai na Task 11; o formato do callback `publish:id:row` é mantido para não quebrar o bot).

2e. Remover o comentário/aviso antigo `"Aviso: sem imagem de capa."` (linhas 345-346) — o novo fluxo já loga.

- [ ] **Step 3: Verificação**

Run: `python -m py_compile execution/run_releases.py && python -m pytest tests/ -v`
Expected: compila; todos os testes PASS.

Run (integração leve, sem publicar): `python execution/run_releases.py --dry-run --max 2`
Expected: roda até o fim sem exceção (dry-run para antes da imagem; valida imports e fluxo).

- [ ] **Step 4: Commit**

```bash
git add execution/run_releases.py
git commit -m "feat: gate humano de imagem — sem foto aprovada vira card de pendência no Telegram"
```

---

### Task 10: pautas search-first

**Files:**
- Modify: `execution/search_sources.py` (parâmetro `--days`)
- Rewrite: `execution/run_pauta_generate.py`
- Modify: `execution/run_pauta_produce.py` (ler pauta de `.tmp/pautas_semana.json` + usar fontes armazenadas)
- Test: `tests/test_pauta_generate.py` (criar)

**Interfaces:**
- Produces:
  - `search_sources.py --query Q [--days 7]` — quando `--days` presente, envia `"topic": "news", "days": N` ao Tavily.
  - `run_pauta_generate.coletar_achados() -> list[dict]` — roda as queries fixas, deduplica por URL; cada achado: `{"title", "url", "snippet", "score", "published_date"}`.
  - `run_pauta_generate.validar_pautas(pautas: list[dict], urls_validas: set[str]) -> list[dict]` — remove pautas sem fonte válida; filtra URLs inventadas.
  - Estado semanal: `.tmp/pautas_semana.json` — `{"<pauta_id>": {"titulo", "keyword", "categoria", "wp_category_id", "justificativa", "tipo", "fontes": [{"title","url","snippet"}]}}` (pauta_id = "1".."10", sobrescrito a cada segunda).
  - `run_pauta_produce.py --pauta-id N` lê desse arquivo (não mais do Sheets).

- [ ] **Step 1: Escrever teste que falha**

Criar `tests/test_pauta_generate.py`:

```python
"""Testa validação determinística anti-alucinação das pautas."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "execution"))


def test_validar_pautas_descarta_sem_fonte():
    from run_pauta_generate import validar_pautas
    urls = {"https://americana.sp.gov.br/evento-x", "https://g1.globo.com/y"}
    pautas = [
        {"titulo": "Real", "fontes": ["https://americana.sp.gov.br/evento-x"]},
        {"titulo": "Inventada", "fontes": []},
        {"titulo": "URL alucinada", "fontes": ["https://naoexiste.fake/z"]},
        {"titulo": "Mista", "fontes": ["https://naoexiste.fake/z", "https://g1.globo.com/y"]},
    ]
    aprovadas = validar_pautas(pautas, urls)
    titulos = [p["titulo"] for p in aprovadas]
    assert titulos == ["Real", "Mista"]
    # URLs alucinadas removidas da pauta mista
    assert aprovadas[1]["fontes"] == ["https://g1.globo.com/y"]
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `python -m pytest tests/test_pauta_generate.py -v`
Expected: FAIL — `validar_pautas` não existe.

- [ ] **Step 3: `search_sources.py` — parâmetro `--days`**

Em `search_sources(query, max_results, min_score)` adicionar parâmetro `days: int = 0` e no `body` (linha 59-67):

```python
    if days > 0:
        body["topic"] = "news"
        body["days"] = days
```

No `main()`, adicionar `parser.add_argument("--days", type=int, default=0, help="Restringe a resultados dos últimos N dias (topic=news)")` e passar `days=args.days`.

- [ ] **Step 4: Reescrever `execution/run_pauta_generate.py`**

Substituir o arquivo inteiro por:

```python
"""
run_pauta_generate.py — Pautas semanais 100% baseadas em fontes reais (search-first).

Fluxo:
  1. Coleta determinística: queries fixas no Tavily (últimos 7 dias, região)
  2. Curadoria via modelo criativo: agrupa achados em até 10 pautas com fontes
  3. Validação determinística: pauta sem fonte real coletada = descartada
  4. Salva .tmp/pautas_semana.json + envia lista ao Telegram com links das fontes
  5. GSC/GA entram apenas como critério de priorização

Uso:
    python execution/run_pauta_generate.py
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
PAUTAS_FILE = PROJECT_DIR / ".tmp" / "pautas_semana.json"

# Queries fixas — cobertura das 4 cidades + agenda regional
QUERIES = [
    "agenda cultural Americana SP esta semana",
    "eventos fim de semana Americana SP",
    "agenda cultural Santa Bárbara d'Oeste",
    "eventos Santa Bárbara d'Oeste esta semana",
    "eventos culturais Nova Odessa SP",
    "o que fazer Nova Odessa fim de semana",
    "programação cultural Sumaré SP",
    "eventos Sumaré esta semana",
    "shows teatro região de Americana Campinas",
    "cursos oficinas gratuitas Americana Santa Bárbara",
]


def _run_json(args: list[str]) -> dict | list | None:
    result = subprocess.run(
        ["python"] + args, capture_output=True, text=True,
        encoding="utf-8", errors="replace", cwd=str(PROJECT_DIR),
    )
    if result.returncode != 0:
        print(f"[pauta_gen] Aviso em {Path(args[0]).name}:\n{result.stderr[:500]}", file=sys.stderr)
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def coletar_achados() -> list[dict]:
    """Roda todas as queries no Tavily e deduplica por URL."""
    achados: dict[str, dict] = {}
    for q in QUERIES:
        print(f"[pauta_gen] Buscando: '{q}'...", file=sys.stderr)
        result = _run_json([str(SCRIPT_DIR / "search_sources.py"),
                            "--query", q, "--max", "5", "--days", "7"])
        if not result:
            continue
        for s in result.get("sources", []):
            url = s.get("url", "")
            if url and url not in achados:
                achados[url] = s
    print(f"[pauta_gen] {len(achados)} achado(s) único(s).", file=sys.stderr)
    return list(achados.values())


def curar_pautas(achados: list[dict], gsc_ctx: str, ga_ctx: str) -> list[dict]:
    """Modelo criativo agrupa achados reais em até 10 pautas com fontes citadas."""
    sys.path.insert(0, str(SCRIPT_DIR))
    from llm_call import llm_call_json, creative_model

    achados_texto = "\n".join(
        f"[{i+1}] {a.get('title','')} — {a.get('url','')}\n    {a.get('snippet','')[:280]}"
        for i, a in enumerate(achados)
    )
    prioridade = ""
    if gsc_ctx:
        prioridade += f"\n\n{gsc_ctx}"
    if ga_ctx:
        prioridade += f"\n\n{ga_ctx}"

    system = """Você é o editor-chefe do +blog, portal de cultura e diversão de Americana, Santa Bárbara d'Oeste (SBO), Nova Odessa e Sumaré (região de Campinas, SP).

Você receberá ACHADOS REAIS da web (título, URL, trecho). Sua tarefa é agrupá-los em até 10 sugestões de pauta para a semana.

REGRAS ABSOLUTAS:
- Cada pauta DEVE citar em "fontes" as URLs exatas dos achados que a embasam (copie a URL literal).
- Só afirme o que está nos trechos. NUNCA invente evento, data, local ou atração.
- Se um achado não tem relação com cultura/diversão nas 4 cidades, ignore-o.
- Se os achados não renderem 10 pautas, retorne menos. Qualidade > quantidade.
- Máx 3 pautas do mesmo tipo (Agenda|Lista|Explicativa|Retrospectiva|Antevisão).
- Título SEO: máx 65 chars, cidade + tema principal.
- Use os dados de priorização (GSC/GA), se presentes, para ordenar por potencial de busca.

Categorias WordPress:
Música: 23 | Arte: 22 | Audiovisual: 533 | Literatura: 540 | Educação: 384
Diversão: 11 | Cultura: 13 | Rolês: 19 | Comida: 10 | Eventos: 12

Retorne APENAS JSON:
{"pautas": [{
  "titulo": "...",
  "keyword": "...",
  "categoria": "...",
  "wp_category_id": 19,
  "justificativa": "...",
  "tipo": "Agenda|Lista|Explicativa|Retrospectiva|Antevisão",
  "fontes": ["url1", "url2"]
}]}"""

    hoje = datetime.now().strftime("Semana de %d/%m/%Y")
    user = f"{hoje}\n\nACHADOS REAIS DA WEB:\n{achados_texto}{prioridade}"

    try:
        resultado = llm_call_json(system=system, user=user, model=creative_model())
        if isinstance(resultado, dict):
            return resultado.get("pautas", [])
        if isinstance(resultado, list):
            return resultado
        return []
    except Exception as e:
        print(f"[pauta_gen] Erro na curadoria: {e}", file=sys.stderr)
        return []


def validar_pautas(pautas: list[dict], urls_validas: set[str]) -> list[dict]:
    """Anti-alucinação: remove URLs inventadas e descarta pautas sem fonte real."""
    aprovadas = []
    for p in pautas:
        fontes_ok = [u for u in p.get("fontes", []) if u in urls_validas]
        if not fontes_ok:
            print(f"[pauta_gen] DESCARTADA (sem fonte real): {p.get('titulo','')[:60]}", file=sys.stderr)
            continue
        p["fontes"] = fontes_ok
        aprovadas.append(p)
    return aprovadas


def _tentar_contexto(script: str, label: str, formato) -> str:
    data = _run_json([str(SCRIPT_DIR / script)])
    if not data:
        print(f"[pauta_gen] {label} indisponível.", file=sys.stderr)
        return ""
    return formato(data)


def main() -> None:
    print("[pauta_gen] Gerando pautas da semana (search-first)...", file=sys.stderr)

    # 1. Coleta real
    achados = coletar_achados()
    if not achados:
        subprocess.run(["python", str(SCRIPT_DIR / "telegram_notify.py"), "send-text",
                        "--message", "⚠️ Pautas da semana: nenhuma fonte encontrada na web. "
                                     "Sem pautas confiáveis para sugerir."],
                       cwd=str(PROJECT_DIR))
        sys.exit(0)

    # 2. Priorização (opcional)
    def _fmt_gsc(data):
        linhas = ["Dados GSC (queries com volume, para priorizar):"]
        items = data if isinstance(data, list) else data.get("rows", [])
        for item in items[:20]:
            q = item.get("query", "?")
            linhas.append(f"  - '{q}': {item.get('impressions', 0)} impressões")
        return "\n".join(linhas)

    def _fmt_ga(data):
        linhas = ["Dados GA4 (posts mais lidos, para priorizar):"]
        items = data if isinstance(data, list) else data.get("rows", [])
        for i, item in enumerate(items[:10], 1):
            linhas.append(f"  {i}. {item.get('titulo', item.get('pagePath', '?'))}: "
                          f"{item.get('views', 0)} views")
        return "\n".join(linhas)

    gsc_ctx = _tentar_contexto("gsc_report.py", "GSC", _fmt_gsc)
    ga_ctx = _tentar_contexto("ga_report.py", "GA4", _fmt_ga)

    # 3. Curadoria + validação anti-alucinação
    urls_validas = {a["url"] for a in achados}
    por_url = {a["url"]: a for a in achados}
    pautas = validar_pautas(curar_pautas(achados, gsc_ctx, ga_ctx), urls_validas)

    if not pautas:
        subprocess.run(["python", str(SCRIPT_DIR / "telegram_notify.py"), "send-text",
                        "--message", "⚠️ Pautas da semana: nenhuma pauta com fonte "
                                     "confirmada. Nada foi inventado."],
                       cwd=str(PROJECT_DIR))
        sys.exit(0)

    # 4. Salva estado semanal com fontes completas
    registro = {}
    lista_telegram = []
    for i, p in enumerate(pautas[:10], 1):
        pauta_id = str(i)
        registro[pauta_id] = {
            "titulo": p.get("titulo", ""),
            "keyword": p.get("keyword", ""),
            "categoria": p.get("categoria", ""),
            "wp_category_id": p.get("wp_category_id", 12),
            "justificativa": p.get("justificativa", ""),
            "tipo": p.get("tipo", ""),
            "fontes": [
                {"title": por_url[u].get("title", ""), "url": u,
                 "snippet": por_url[u].get("snippet", "")}
                for u in p.get("fontes", [])
            ],
        }
        primeira_fonte = p["fontes"][0] if p.get("fontes") else ""
        lista_telegram.append({
            "pauta_id": pauta_id, "numero": i,
            "titulo": f"{p.get('titulo', '')} · fonte: {primeira_fonte}",
        })
    PAUTAS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PAUTAS_FILE.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")

    # 5. Telegram
    subprocess.run(["python", str(SCRIPT_DIR / "telegram_notify.py"), "send-pauta-list",
                    "--data", json.dumps(lista_telegram, ensure_ascii=False)],
                   cwd=str(PROJECT_DIR))

    print(f"[pauta_gen] ✅ {len(registro)} pauta(s) com fonte enviadas ao Telegram.", file=sys.stderr)
    print(json.dumps({"pautas": lista_telegram}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Adaptar `execution/run_pauta_produce.py`**

5a. Substituir a leitura da pauta (linhas 283-296) por:

```python
    PAUTAS_FILE = PROJECT_DIR / ".tmp" / "pautas_semana.json"
    if not PAUTAS_FILE.exists():
        print(f"[run_pauta_produce] {PAUTAS_FILE} não existe — rode run_pauta_generate antes.", file=sys.stderr)
        sys.exit(1)
    todas = json.loads(PAUTAS_FILE.read_text(encoding="utf-8"))
    pauta = todas.get(pauta_id)
    if not pauta:
        print(f"[run_pauta_produce] Pauta #{pauta_id} não encontrada.", file=sys.stderr)
        sys.exit(1)
```

5b. Remover `_update_status` (linhas 63-69) e todas as suas chamadas (linhas 299, 313, 329, 406, 427) — o status vivia no Sheets.

5c. Substituir a busca de fontes (linhas 301-322) por: usar as fontes armazenadas + busca complementar:

```python
    fontes = list(pauta.get("fontes", []))
    # Busca complementar por conteúdo mais recente sobre a keyword
    query = pauta.get("keyword") or pauta.get("titulo", "")
    extra = _run_json([str(SCRIPT_DIR / "search_sources.py"), "--query", query, "--max", "3"])
    if extra:
        urls_existentes = {f.get("url") for f in fontes}
        for s in extra.get("sources", []):
            if s.get("url") not in urls_existentes:
                fontes.append(s)

    if not fontes:
        print("[run_pauta_produce] Pauta sem fontes — não deveria acontecer (validada na geração).", file=sys.stderr)
        subprocess.run(["python", str(SCRIPT_DIR / "telegram_notify.py"), "send-text",
                        "--message", f"⚠️ Pauta #{pauta_id} sem fontes. Produção cancelada."],
                       cwd=str(PROJECT_DIR))
        sys.exit(0)
    print(f"[run_pauta_produce] {len(fontes)} fonte(s).", file=sys.stderr)
```

5d. Em `_llm_escrever_post` (linha 219) e `_llm_legenda_ig` (linha 270), usar o modelo criativo:

```python
    from llm_call import llm_call_json, creative_model
    ...
        return llm_call_json(system=system, user=user, model=creative_model())
```

(e o equivalente com `llm_call(..., model=creative_model())` na legenda).

5e. Remover a linha `IG_MODEL = ...` (linha 32) e o bloco "9. Salva legenda IG no Sheets" (linhas 412-424). A legenda IG passa a ir no card: adicionar aos args do `send-release` final (linha 435-444): `"--ig-image", ig_path, "--ig-caption", legenda` quando `ig_path` existir, e trocar `"--sheets-row-id", pauta_id` por `"--sheets-row-id", "0"`.

- [ ] **Step 6: Rodar testes e verificação**

Run: `python -m pytest tests/test_pauta_generate.py -v && python -m py_compile execution/run_pauta_generate.py execution/run_pauta_produce.py execution/search_sources.py`
Expected: PASS + compila.

Run (integração real, requer TAVILY_API_KEY no .env): `python execution/run_pauta_generate.py`
Expected: log mostra achados reais, pautas descartadas sem fonte (se houver) e lista final no Telegram com URLs de fontes visíveis. Conferir manualmente que as URLs abrem e são reais.

- [ ] **Step 7: Commit**

```bash
git add execution/run_pauta_generate.py execution/run_pauta_produce.py execution/search_sources.py tests/test_pauta_generate.py
git commit -m "feat: pautas search-first — só sugestões com fonte real, validação anti-alucinação"
```

---

### Task 11: remoção do Google Sheets

**Files:**
- Delete: `execution/sheets_read.py`, `execution/sheets_write.py`, `token_sheets.json`
- Modify: `execution/run_releases.py`, `execution/telegram_notify.py`, `start.sh`, `requirements.txt` (manter google-* — Gmail ainda usa), `setup_google_auth.py` (remover parte Sheets se houver)

**Interfaces:**
- Consumes: `wp_publish.py find --slug` (Task 5).
- Produces: pipeline sem nenhuma referência a Sheets; dedup de release via WP + arquivo local.

- [ ] **Step 1: `run_releases.py` — dedup via WordPress**

1a. Remover a função `_load_processed_from_sheets` (linhas 58-73) e seu uso no `main()` (linhas 527-529), e o parâmetro `processed_subjects` de `processar_email` (com o bloco "Deduplicação 2", linhas 282-287).

1b. Adicionar dedup por slug antes de criar o rascunho — em `processar_email`, logo após montar `slug` (linha 329):

```python
    # Dedup persistente: já existe post com este slug no WP?
    existente = _run_json([str(SCRIPT_DIR / "wp_publish.py"), "find", "--slug", slug])
    if existente and existente.get("exists"):
        print(f"[run_releases]   Post já existe no WP (#{existente['post_id']}), pulando.", file=sys.stderr)
        _mark_processed(email_id)
        return {"email_id": email_id, "relevante": True, "motivo": "Duplicado no WP"}
```

(colocar depois do `if dry_run: return ...` para não gastar chamada em dry-run — mover o check para logo após o bloco dry_run, linha 341.)

1c. Remover o bloco "11. Registra no Sheets" (linhas 449-457) e o bloco `if ig_url:` de legenda-ig (linhas 459-471). A variável `sheets_row_id` deixa de existir — usar `"0"` direto no notify (já feito na Task 9).

- [ ] **Step 2: `telegram_notify.py` — `_execute_action` sem Sheets**

Substituir `_execute_action` (linhas 454-502) por:

```python
def _execute_action(action: str, post_id: int, sheets_row_id: str, user: str,
                    ig_image_path: str = "", ig_caption: str = "") -> dict:
    """Executa Publicar (site), Aprovar IG ou Descartar. (sheets_row_id: legado, ignorado)"""
    import subprocess
    script_dir = Path(__file__).parent

    if action == "publish":
        wp_result = subprocess.run(
            ["python3", str(script_dir / "wp_publish.py"), "publish", "--post-id", str(post_id)],
            capture_output=True, text=True,
        )
        wp_data = json.loads(wp_result.stdout) if wp_result.returncode == 0 else {}
        new_status = "Publicado"
        url = wp_data.get("url", "")
        cmd_send_text(f"✅ <b>Publicado!</b>\n{url}" if url else f"✅ Post #{post_id} publicado.")

    elif action == "publish_ig":
        new_status = "Aprovado"
        cmd_send_text(
            f"📸 Post #{post_id} aprovado para Instagram.\n"
            f"A arte e a legenda estão na mensagem acima — copie e poste."
        )

    else:  # discard
        subprocess.run(
            ["python3", str(script_dir / "wp_publish.py"), "trash", "--post-id", str(post_id)],
            capture_output=True, text=True,
        )
        new_status = "Descartado"
        cmd_send_text(f"🗑 Post #{post_id} descartado por {user}.")

    return {"post_id": post_id, "action": action, "status": new_status}
```

- [ ] **Step 3: `start.sh` — remover reconstrução do token Sheets**

Remover o bloco:

```bash
if [ -n "$SHEETS_TOKEN_B64" ]; then
    echo "$SHEETS_TOKEN_B64" | base64 -d > /app/token_sheets.json
    echo "[start] token_sheets.json reconstituído de SHEETS_TOKEN_B64"
fi
```

- [ ] **Step 4: Deletar arquivos e conferir referências**

```bash
git rm execution/sheets_read.py execution/sheets_write.py
rm -f token_sheets.json
grep -rn "sheets_" execution/ start.sh crontab | grep -v "sheets_row_id"
```

Expected: nenhum resultado além de `sheets_row_id` (parâmetro legado mantido no formato de callback). Se `setup_google_auth.py` tiver seção Sheets, removê-la também.

- [ ] **Step 5: Rodar tudo**

Run: `python -m pytest tests/ -v && python -m py_compile execution/*.py`
Expected: PASS + tudo compila.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: remove Google Sheets — dedup via WordPress, estado 100% em .tmp/"
```

---

### Task 12: limpeza, smoke test e diretivas

**Files:**
- Modify: `execution/run_releases.py:41` (remover `IG_MODEL`)
- Create: `execution/smoke_test.py`
- Modify: `directives/pauta-semanal.md`, `directives/release-to-post.md`, `directives/social-instagram.md`, `directives/image-select-resize.md`

- [ ] **Step 1: Remover `IG_MODEL`**

Deletar a linha 41 de `execution/run_releases.py` (`IG_MODEL = str(PROJECT_DIR / "assets" / "instagram" / "6.jpg")`). (A de `run_pauta_produce.py` já saiu na Task 10.)

Run: `grep -rn "IG_MODEL\|6.jpg" execution/ --include="*.py"`
Expected: nenhum resultado.

- [ ] **Step 2: Criar `execution/smoke_test.py`**

```python
"""
smoke_test.py — Valida o pipeline editorial de ponta a ponta SEM publicar nada.

Roda: extrair_fatos → hierarquia → gerar_arte_com_validacao → gerar_legenda →
arte IG (com imagem local). Não toca WP, Telegram, Gmail nem Sheets.

Requer: OPENROUTER_API_KEY no .env.

Uso:
    python execution/smoke_test.py [--image "caminho/foto.jpg"]
"""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

RELEASE_EXEMPLO = """
Oficina gratuita de efeitos especiais para cinema em Americana

A Secretaria de Cultura de Americana promove nos dias 20 e 21 de julho uma
oficina gratuita de efeitos especiais e maquiagem cênica para cinema, na
Estação Cultura (Rua Padre Anchieta, 46, Centro). As atividades acontecem
das 14h às 17h e são voltadas a jovens a partir de 14 anos. As inscrições
podem ser feitas pelo site da prefeitura até 18 de julho. As vagas são
limitadas a 30 participantes por turma. A oficina será ministrada pelo
caracterizador João Silva, com 15 anos de experiência em produções
audiovisuais. Fotos: Divulgação/Prefeitura de Americana.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test do pipeline editorial")
    parser.add_argument("--image", default="", help="Foto local para a arte IG (opcional)")
    args = parser.parse_args()

    from editorial import (extrair_fatos, extract_editorial_hierarchy,
                           avaliar_relevancia, gerar_arte_com_validacao, gerar_legenda)

    print("1/5 Extraindo fatos...", file=sys.stderr)
    fatos = extrair_fatos(RELEASE_EXEMPLO)
    assert fatos.get("cidade"), f"fatos sem cidade: {fatos}"

    print("2/5 Avaliando relevância...", file=sys.stderr)
    aval = avaliar_relevancia(RELEASE_EXEMPLO, fatos)
    assert aval.get("relevante") is True, f"release exemplo deveria ser relevante: {aval}"

    print("3/5 Hierarquia + conteúdo + arte...", file=sys.stderr)
    hierarchy = extract_editorial_hierarchy(RELEASE_EXEMPLO, fatos)
    post = gerar_arte_com_validacao(RELEASE_EXEMPLO, fatos, aval,
                                    release_titulo="Oficina de efeitos especiais",
                                    hierarchy=hierarchy)
    assert post.get("titulo_site"), "sem titulo_site"
    assert not post.get("_fallback"), f"conteúdo caiu em fallback: {post.get('_fallback')}"
    arte = post.get("texto_arte", {})
    assert arte.get("titulo_principal"), "sem título de arte"

    print("4/5 Legenda IG...", file=sys.stderr)
    legendas = gerar_legenda(fatos, post.get("resumo_telegram", ""),
                             arte_instagram=arte, hierarchy=hierarchy)
    assert legendas.get("legenda_curta"), "sem legenda"
    assert not legendas.get("_fallback"), f"legenda caiu em fallback"
    assert "#" not in legendas["legenda_curta"], "legenda com hashtag"

    print("5/5 Arte IG...", file=sys.stderr)
    imagem = args.image
    if not imagem:
        from PIL import Image
        p = PROJECT_DIR / ".tmp" / "smoke_cover.jpg"
        p.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1600, 900), (120, 60, 140)).save(p, "JPEG", quality=85)
        imagem = str(p)

    from instagram_image import generate_ig_image
    result = generate_ig_image(
        cover_path=imagem, category=post.get("categoria", "Cultura"),
        title=arte["titulo_principal"], slug="smoke",
        output_dir=str(PROJECT_DIR / ".tmp"),
        subtitle=arte.get("linha_apoio", ""),
    )
    assert Path(result["path"]).exists()

    print(json.dumps({
        "ok": True,
        "titulo_site": post["titulo_site"],
        "titulo_arte": arte["titulo_principal"],
        "linha_apoio": arte.get("linha_apoio", ""),
        "legenda_curta": legendas["legenda_curta"],
        "arte_path": result["path"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Rodar o smoke test**

Run: `python execution/smoke_test.py --image "Oficina Efeitos especiais Americana SP.jpg"`
Expected: JSON final com `"ok": true`, título de arte coerente com a oficina, legenda em blocos com voz editorial (sem hashtag, sem "confira"). Abrir `.tmp/smoke_ig.webp` e conferir a diagramação.

- [ ] **Step 4: Atualizar diretivas**

Reescrever as seções desatualizadas (documentos vivos, conforme CLAUDE.md do projeto):

- `directives/pauta-semanal.md`: fluxo agora é search-first — coleta Tavily (10 queries fixas, 7 dias) → curadoria com `CREATIVE_MODEL` → validação de URLs → `.tmp/pautas_semana.json` → Telegram com links das fontes. Regra: pauta sem fonte real é descartada; zero pautas = aviso, nunca invenção. Produção lê fontes do arquivo semanal.
- `directives/release-to-post.md`: registrar o roteamento de modelos (mecânico=`EDITORIAL_MODEL`, criativo=`CREATIVE_MODEL`), o dedup via `wp_publish find --slug`, a remoção do Sheets, e que fallbacks agora aparecem como ⚠️ no card.
- `directives/social-instagram.md`: título da arte validado por `title_fits` (preflight visual, ≤3 linhas, fonte ≥60pt) — não mais por contagem de palavras; layout ancorado acima do logo; legendas vêm no card do Telegram (Sheets removido).
- `directives/image-select-resize.md`: vision tri-state (`yes/no/unavailable`); 503 nunca aprova automaticamente; sem placeholder; sem imagem aprovada → card `send-image-pending` com botões `[Usar sugestão]/[Vou enviar foto]`; foto enviada no chat resolve a pendência.

- [ ] **Step 5: Rodar a suíte completa**

Run: `python -m pytest tests/ -v && python -m py_compile execution/*.py`
Expected: todos PASS, tudo compila.

- [ ] **Step 6: Commit final**

```bash
git add -A
git commit -m "feat: smoke test, remoção de referência morta e diretivas atualizadas"
```

---

### Task 13: verificação de produção (manual, com o usuário)

**Files:** nenhum — checklist operacional.

- [ ] **Step 1: Configurar env vars no Coolify**

Adicionar `CREATIVE_MODEL=google/gemini-2.5-flash`. NÃO remover as vars do Sheets ainda (remoção só após confirmar deploy saudável).

- [ ] **Step 2: Push + redeploy**

```bash
git push origin main
curl -X POST -H "Authorization: Bearer $COOLIFY_TOKEN" \
  "https://serv2.criatoin.com.br/api/v1/deploy?uuid=ksko44gg48k0wsg04sosscsc&force=true"
```

(Token está na memória do projeto/Coolify — confirmar com o usuário antes do deploy, conforme regra do CLAUDE.md de não mexer no Coolify sem aprovação.)

- [ ] **Step 3: Testes em produção (roteiro para o usuário)**

1. Enviar um release de teste por email com foto boa → conferir card completo no Telegram, legenda com a nova voz, arte com diagramação correta.
2. Enviar um release só com flyer/logo → conferir card "⚠️ Sem imagem adequada"; testar `[Vou enviar foto]` respondendo com uma foto; conferir card completo na sequência.
3. Rodar `python3 execution/run_pauta_generate.py` no container (ou aguardar segunda 9h) → conferir que toda pauta listada tem link de fonte real e que os links abrem.
4. Clicar `[Produzir N]` numa pauta → conferir matéria baseada nas fontes.
5. Após 1 semana estável: remover env vars `SHEETS_ID`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`, `SHEETS_TOKEN_B64` do Coolify.
