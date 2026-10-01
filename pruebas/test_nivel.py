"""CP-28: regla léxica del nivel requerido (decisión I5)."""

import pytest

from ingesta.extraccion.nivel import asignar_nivel


def _nivel(params, texto, termino):
    inicio = texto.index(termino)
    return asignar_nivel(texto, inicio, inicio + len(termino), params.nivel_requerido)


def test_cp28_marcador_explicito(params):
    assert _nivel(params, "Python avanzado", "Python") == "avanzado"
    assert _nivel(params, "Conocimientos básicos de Docker", "Docker") == "básico"
    assert _nivel(params, "Nivel intermedio de SQL", "SQL") == "intermedio"
    assert _nivel(params, "Sólidos conocimientos en Java", "Java") == "avanzado"


def test_cp28_sin_marcador_se_omite(params):
    assert _nivel(params, "Manejo de Git", "Git") is None
    assert _nivel(params, "3 años de experiencia en Java", "Java") is None


def test_cp28_con_dos_marcadores_gana_el_mas_cercano(params):
    texto = "Python avanzado y Docker básico"
    assert _nivel(params, texto, "Python") == "avanzado"
    assert _nivel(params, texto, "Docker") == "básico"


@pytest.mark.parametrize(
    ("texto", "termino"),
    [
        ("Habilidad avanzada en Wireshark", "Wireshark"),
        ("Habilidades avanzadas en Wireshark", "Wireshark"),
        ("Comprensión sólida de BGP", "BGP"),
        ("Bases sólidas de SQL", "SQL"),
        ("Experta en Linux", "Linux"),
    ],
)
def test_cp28_reconoce_las_formas_femeninas_del_marcador(params, texto, termino):
    assert _nivel(params, texto, termino) == "avanzado"


def test_cp28_un_marcador_mas_lejos_del_tope_no_cuenta(params):
    tope = params.nivel_requerido.distancia_maxima
    dentro = "Docker" + " " * tope + "avanzado"
    fuera = "Docker" + " " * (tope + 1) + "avanzado"
    assert _nivel(params, dentro, "Docker") == "avanzado"
    assert _nivel(params, fuera, "Docker") is None
