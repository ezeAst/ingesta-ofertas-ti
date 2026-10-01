"""Consultas y resaltado del panel."""

import pytest

from ingesta.campana import ejecutar_campana
from ingesta.panel.datos import avisos, detalle, resaltar, unidades_resaltadas

from .test_campana import simular_portales


def _c(termino, inicio, fin, via="literal", puntaje=None):
    return {
        "termino": termino,
        "inicio": inicio,
        "fin": fin,
        "via": via,
        "puntaje": puntaje,
        "unidad": 0,
    }


def test_resaltar_marca_literal_y_semantica_y_escapa_html():
    texto = "Python <avanzado> y backups"
    salida = resaltar(
        texto, [_c("Python", 0, 6), _c("Alta disponibilidad", 20, 27, "semantica", 0.91)]
    )
    assert '<mark class="lit"' in salida and '<mark class="sem"' in salida
    assert "&lt;avanzado&gt;" in salida
    assert "Alta disponibilidad (0.910)" in salida


def test_resaltar_une_terminos_del_mismo_tramo():
    salida = resaltar("Experiencia con EKS", [_c("AWS", 16, 19), _c("Kubernetes", 16, 19)])
    assert salida.count("<mark") == 1 and "AWS, Kubernetes" in salida


@pytest.mark.integracion
@pytest.mark.respx(assert_all_called=False)
def test_avisos_y_detalle_desde_las_trazas(respx_mock, bd, dep, params_bow):
    simular_portales(respx_mock, params_bow)
    ejecutar_campana(dep())
    descartes = avisos(bd, destino="descartado")
    assert {f["motivo"] for f in descartes} == {
        "No es de TI",
        "Duplicado",
        "Sin competencias",
        "Rechazado por el esquema",
    }
    con_python = avisos(bd, texto="python")  # Bumeran 1 y su duplicado en Computrabajo
    assert len(con_python) == 2
    assert all("python" in f["título"].lower() for f in con_python)
    d = detalle(bd, "Bumeran", "1")
    assert d["crudo"]["contenido"]["titulo"] == "Desarrollador Python"
    assert d["oferta"]["fuente"]["id_aviso"] == "1" and d["descarte"] is None
    html_unidades = unidades_resaltadas(d["traza"])
    assert any('<mark class="lit"' in h for _, h in html_unidades)
