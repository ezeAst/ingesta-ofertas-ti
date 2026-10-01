"""Prueba de humo del panel: la app completa se renderiza sin errores sobre datos de prueba."""

import pytest
from streamlit.testing.v1 import AppTest

from ingesta.campana import ejecutar_campana
from ingesta.config import RAIZ

from .test_campana import simular_portales

APP = str(RAIZ / "src" / "ingesta" / "panel" / "app.py")

pytestmark = [pytest.mark.integracion, pytest.mark.respx(assert_all_called=False)]


def test_el_panel_muestra_las_cuatro_pestanas(respx_mock, bd, dep, params_bow, monkeypatch):
    simular_portales(respx_mock, params_bow)
    respx_mock.route(host="embeddings").pass_through()
    ejecutar_campana(dep())
    monkeypatch.setenv("MONGO_BD", bd.name)

    at = AppTest.from_file(APP, default_timeout=120).run()

    assert not at.exception, at.exception
    etiquetas = [t.label for t in at.tabs]
    for pestana in ("▶️ Pipeline", "📄 Ofertas", "🗑️ Descartes", "🧩 Candidatos"):
        assert pestana in etiquetas
    assert any(m.label == "Publicados" and m.value == "3" for m in at.sidebar.metric)
