"""CP-32: exportación del vocabulario de R 1.3 a JSON versionado."""

import pytest

from ingesta.vocabulario import (
    RAMAS,
    Vocabulario,
    agregar_termino,
    agregar_variante,
    exportar_desde_xlsx,
    guardar_version,
)

from .conftest import XLSX_VOCABULARIO

requiere_xlsx = pytest.mark.skipif(
    not XLSX_VOCABULARIO.exists(), reason="el xlsx de R 1.3 no está montado en /resultados"
)


@requiere_xlsx
def test_cp32_exporta_los_conteos_de_r13():
    datos = exportar_desde_xlsx(XLSX_VOCABULARIO)
    terminos = datos["terminos"]
    assert len(terminos) == 322
    assert len({t["categoria"] for t in terminos}) == 26
    assert sum(len(t["literales"]) for t in terminos) == 626
    assert sum(len(t["descriptivas"]) for t in terminos) == 1929
    assert set(datos["categorias"]) == set(RAMAS)


@requiere_xlsx
def test_cp32_recorta_anotaciones_y_asigna_rama():
    datos = exportar_desde_xlsx(XLSX_VOCABULARIO)
    python = next(t for t in datos["terminos"] if t["nombre"] == "Python")
    assert "Phyton" in python["literales"]
    assert not any("(" in v for t in datos["terminos"] for v in t["literales"])
    assert datos["categorias"]["Trabajo en equipo"] == "transversal"
    assert datos["categorias"]["Lenguajes de programación"] == "técnica"


def _vocab_minimo():
    return {
        "categorias": {"Lenguajes de programación": "técnica", "Comunicación": "transversal"},
        "terminos": [
            {
                "nombre": "Python",
                "categoria": "Lenguajes de programación",
                "literales": ["Python 3"],
                "descriptivas": [],
            }
        ],
    }


def test_guardar_version_solo_crea_una_nueva_si_el_contenido_cambia(tmp_path):
    ruta1 = guardar_version(_vocab_minimo(), tmp_path)
    ruta2 = guardar_version(_vocab_minimo(), tmp_path)
    assert ruta1 == ruta2
    assert ruta1.name == "vocabulario_v001.json"
    vocab = Vocabulario.cargar_vigente(tmp_path)
    assert vocab.version == 1
    assert vocab.rama("Comunicación") == "transversal"


def test_agregar_variante_y_termino_generan_versiones_nuevas(tmp_path):
    guardar_version(_vocab_minimo(), tmp_path)
    datos = Vocabulario.cargar_vigente(tmp_path).datos
    guardar_version(agregar_variante(datos, "Python", "Py3", descriptiva=False), tmp_path)
    vocab = Vocabulario.cargar_vigente(tmp_path)
    assert vocab.version == 2
    assert "Py3" in vocab.termino("Python")["literales"]

    nuevo = agregar_termino(vocab.datos, "Mojo", "Lenguajes de programación")
    guardar_version(nuevo, tmp_path)
    vocab = Vocabulario.cargar_vigente(tmp_path)
    assert vocab.version == 3
    assert vocab.termino("Mojo")["categoria"] == "Lenguajes de programación"


def test_agregar_termino_rechaza_una_categoria_que_no_existe():
    with pytest.raises(ValueError, match="categoría"):
        agregar_termino(_vocab_minimo(), "Algo", "Categoría inventada")
