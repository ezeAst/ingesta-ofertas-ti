"""CP-09 (parte estática): el corpus y los secretos no salen de la máquina (compromiso 7)."""

import re

from ingesta.config import RAIZ


def test_cp09_gitignore_excluye_secretos_y_datos():
    ignorados = (RAIZ / ".gitignore").read_text(encoding="utf-8").splitlines()
    for patron in (".env", "datos/", "exportaciones/", "respaldos/", "logs/"):
        assert patron in ignorados, patron


def test_cp09_ningun_puerto_se_publica_fuera_de_la_maquina():
    compose = (RAIZ / "compose.yaml").read_text(encoding="utf-8")
    publicados = re.findall(r'^\s*-\s*"([^"]+:\d+)"', compose, flags=re.MULTILINE)
    assert publicados, "no se encontraron puertos publicados"
    assert all(p.startswith("127.0.0.1:") for p in publicados), publicados


def test_cp09_la_imagen_no_copia_secretos_ni_datos():
    excluidos = (RAIZ / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for patron in (".env", "datos", "exportaciones", "respaldos"):
        assert patron in excluidos, patron
