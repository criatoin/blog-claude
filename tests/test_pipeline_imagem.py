"""Regra editorial: a capa é SEMPRE foto do email — sem vision e sem banco de imagens.

run_releases.py tem um guard de horário que encerra no import, então a função
_pipeline_imagem é extraída por AST e executada com dependências falsas.
"""
import ast
import sys
from pathlib import Path

SRC = Path(__file__).parent.parent / "execution" / "run_releases.py"


def _carregar(run_json):
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_pipeline_imagem")
    ns = {"Path": Path, "sys": sys, "SCRIPT_DIR": Path("execution"), "OUTPUT_DIR": ".tmp", "_run_json": run_json}
    exec(compile(ast.Module([fn], []), str(SRC), "exec"), ns)
    return ns["_pipeline_imagem"]


def _fake_run_json(args):
    if args[0].endswith("image_select.py"):
        att = args[2]
        score = {"a.jpg": 3, "b.jpg": 7, "logo.jpg": None}[Path(att).name]
        return {"path": att if score is not None else None, "score": score or 0}
    if args[0].endswith("image_process.py"):
        return {"path": "cover_" + Path(args[args.index("--input") + 1]).name}
    raise AssertionError("não deve chamar image_generate")


def test_usa_melhor_foto_do_email():
    pipe = _carregar(_fake_run_json)
    r = pipe({"attachments": ["x/a.jpg", "x/b.jpg", "x/logo.jpg"]}, "slug", "t")
    assert r["cover_path"] == "cover_b.jpg"


def test_sem_foto_vira_pendencia_sem_banco_de_imagens():
    pipe = _carregar(_fake_run_json)
    r = pipe({"attachments": ["x/logo.jpg"]}, "slug", "t")
    assert r["cover_path"] == "" and r["suggestion_path"] == ""
    assert pipe({"attachments": []}, "slug", "t")["cover_path"] == ""
