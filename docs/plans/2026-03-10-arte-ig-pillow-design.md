# Design — Arte Instagram com Pillow + Link na Planilha

**Data:** 2026-03-10
**Status:** Aprovado

---

## Problema

1. A arte IG gerada não segue o template visual do +blog — o script atual envia apenas a foto ao Gemini com prompt genérico, sem badge, sem título, sem logo.
2. A coluna `path_imagem` na aba Legendas IG salva apenas o caminho local do container (`.tmp/slug_ig.webp`), inacessível fora do servidor.

---

## Solução

### 1. Reescrever `instagram_image.py` — composição Pillow

Substituir a geração via Gemini por composição determinística local usando Pillow.

**Camadas (de baixo para cima):**

```
[1] Foto de capa — smart crop 1080×1350px
[2] Gradiente rosa — overlay nos 45% inferiores
    (transparente → rosa da marca #FF3EB5, ~80% opacidade)
[3] Badge — retângulo arredondado #C8E600 (lima)
             texto preto bold all caps — nome da categoria
[4] Título — branco bold ~52px, máx 3 linhas, abaixo do badge
[5] Logo — PNG circular +blog com máscara (remove fundo branco),
           ~110px, canto inferior direito
```

**Assets necessários:**
- `assets/fonts/Poppins-Bold.ttf` — fonte dos textos (badge + título)
- `assets/instagram/logo_circulo.png` — logo existente (`Logo redondo +blog fundo rosa.png`)

**Saída:** `.tmp/{slug}_ig.webp`, 1080×1350px, <1MB

### 2. Upload para WordPress Media Library

Após gerar a imagem, fazer upload via API WP REST e salvar a URL pública.

**Fluxo:**
1. `instagram_image.py` gera `.tmp/{slug}_ig.webp`
2. `wp_publish.py` recebe novo comando `upload-media --path <arquivo>` → retorna URL pública
3. Pipeline (`run_releases.py` e `run_pauta_produce.py`) salva a URL no Sheets

**Coluna `path_imagem`** passa a conter: `https://maisblog.com.br/wp-content/uploads/...`

---

## Arquivos a modificar

| Arquivo | Mudança |
|---------|---------|
| `execution/instagram_image.py` | Reescrever: composição Pillow, remover Gemini |
| `execution/wp_publish.py` | Adicionar comando `upload-media` |
| `execution/run_releases.py` | Chamar upload-media, salvar URL no Sheets |
| `execution/run_pauta_produce.py` | Idem |
| `assets/fonts/Poppins-Bold.ttf` | Adicionar ao repo |
| `Dockerfile` | Garantir Pillow e fontes disponíveis |
| `directives/social-instagram.md` | Atualizar SOP com novo fluxo |

---

## O que NÃO muda

- Geração da legenda via LLM (`_llm_legenda_ig`) — permanece igual
- Fluxo de callbacks Telegram
- Estrutura da planilha (apenas o valor da coluna `path_imagem` muda de path local para URL)
