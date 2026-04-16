"""
image_select.py — Pontua imagens e retorna a melhor candidata para capa de post.

Score 0-8:
  +2  resolução >= 1920x1080
  +1  resolução >= 1280x720
  +2  aspect ratio dentro da faixa 16:9 (1.6 – 2.0)
  +1  aspect ratio na faixa alargada (1.4 – 2.2)
  +1  dimensões mínimas 800x450
  +1  tamanho do arquivo < 8MB
  +1  orientação landscape

Threshold de aprovação: score >= 2
(baixo por design — fotos reais de email/Flickr valem mais que geradas por IA,
mesmo sendo portrait ou resolução menor. A validação de conteúdo fica para _imagem_relevante.)

Uso:
    python execution/image_select.py --images .tmp/a.jpg .tmp/b.png

Saída JSON para stdout:
    {"path": ".tmp/a.jpg", "score": 6, "width": 1920, "height": 1080, "reason": "..."}
    ou
    {"path": null, "score": 0, "reason": "Nenhuma imagem atingiu score mínimo de 2"}
"""

import argparse
import json
import os
import sys
from pathlib import Path

from PIL import Image


SCORE_THRESHOLD = 2


def score_image(path: str) -> dict:
    """Pontua uma imagem e retorna dict com score e metadados."""
    p = Path(path)
    if not p.exists():
        return {"path": path, "score": -1, "reason": "Arquivo não encontrado"}

    try:
        with Image.open(p) as img:
            width, height = img.size
    except Exception as e:
        return {"path": path, "score": -1, "reason": f"Erro ao abrir imagem: {e}"}

    file_size_mb = p.stat().st_size / (1024 * 1024)
    ratio = width / height if height > 0 else 0

    # Logos e artefatos gráficos tendem a ser muito pequenos — descartar automaticamente
    if file_size_mb < 0.1:
        return {"path": path, "score": 0, "reason": f"Arquivo < 100KB ({file_size_mb*1024:.0f}KB) — provável logo ou ícone"}

    score = 0
    reasons = []

    # Resolução
    if width >= 1920 and height >= 1080:
        score += 2
        reasons.append("res>=1920x1080(+2)")
    elif width >= 1280 and height >= 720:
        score += 1
        reasons.append("res>=1280x720(+1)")

    # Aspect ratio (16:9 = 1.778)
    if 1.6 <= ratio <= 2.0:
        score += 2
        reasons.append("ratio_16:9(+2)")
    elif 1.4 <= ratio <= 2.2:
        score += 1
        reasons.append("ratio_wide(+1)")

    # Dimensões mínimas
    if width >= 800 and height >= 450:
        score += 1
        reasons.append("min_800x450(+1)")

    # Tamanho de arquivo razoável
    if file_size_mb < 8:
        score += 1
        reasons.append("size<8MB(+1)")

    # Landscape
    if width > height:
        score += 1
        reasons.append("landscape(+1)")

    return {
        "path": path,
        "score": score,
        "width": width,
        "height": height,
        "ratio": round(ratio, 3),
        "size_mb": round(file_size_mb, 2),
        "reason": ", ".join(reasons) if reasons else "sem pontos",
    }


def select_best(image_paths: list[str]) -> dict:
    """Avalia todas as imagens e retorna a de maior score."""
    results = [score_image(p) for p in image_paths]
    valid = [r for r in results if r["score"] >= 0]

    if not valid:
        return {"path": None, "score": 0, "reason": "Nenhuma imagem válida fornecida"}

    best = max(valid, key=lambda r: r["score"])

    if best["score"] < SCORE_THRESHOLD:
        return {
            "path": None,
            "score": best["score"],
            "reason": f"Melhor score foi {best['score']} (mínimo {SCORE_THRESHOLD}): {best['path']}",
        }

    return best


def main() -> None:
    parser = argparse.ArgumentParser(description="Seleciona a melhor imagem para capa")
    parser.add_argument("--images", nargs="+", required=True, help="Caminhos das imagens a avaliar")
    args = parser.parse_args()

    result = select_best(args.images)
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
