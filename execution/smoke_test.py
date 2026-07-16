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
