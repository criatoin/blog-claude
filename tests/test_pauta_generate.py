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
