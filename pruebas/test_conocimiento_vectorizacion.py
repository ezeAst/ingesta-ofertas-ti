"""BC-10 y BC-11: cada sincronización queda en `ejecuciones` y la campaña la dispara sin depender
de que Qdrant responda (R 2.4, V11)."""

import pytest
from qdrant_client import QdrantClient

from ingesta.campana import ejecutar_campana, ejecutar_reproceso
from ingesta.conocimiento.vectorizacion import ejecutar_vectorizacion

from .test_campana import simular_portales
from .utiles import insertar_oferta

pytestmark = pytest.mark.integracion


def test_bc10_vectorizacion_queda_en_ejecuciones(bd, qdrant, dep, params_bc):
    for i in range(3):
        insertar_oferta(bd, f"A{i}")
    d = dep(params=params_bc)
    d.qdrant = qdrant

    ejecucion = ejecutar_vectorizacion(d)

    guardada = bd.ejecuciones.find_one({"_id": ejecucion["_id"]})
    assert guardada["modo"] == "vectorizacion"
    assert guardada["estado"] == "exitosa"
    assert guardada["resultados"]["creadas"] == 3
    assert guardada["coleccion"] == "ofertas_pruebas"
    assert isinstance(guardada["duracion_s"], float)


def test_bc11_qdrant_caido_no_tumba_la_campana(respx_mock, bd, dep, params_bc):
    simular_portales(respx_mock, params_bc)
    respx_mock.route(host="127.0.0.1").pass_through()
    d = dep(params=params_bc)
    d.qdrant = QdrantClient(url="http://127.0.0.1:1", timeout=2, check_compatibility=False)

    ejecucion = ejecutar_campana(d)

    assert ejecucion["estado"] == "exitosa"
    assert ejecucion["base_conocimiento"]["estado"] == "desactualizada"
    guardada = bd.ejecuciones.find_one({"_id": ejecucion["_id"]})
    assert guardada["base_conocimiento"]["estado"] == "desactualizada"
    assert guardada["estado"] == "exitosa"


def test_campana_y_reproceso_actualizan_la_base(qdrant, respx_mock, bd, dep, params_bc):
    simular_portales(respx_mock, params_bc)
    respx_mock.route(host="qdrant").pass_through()
    d = dep(params=params_bc)
    d.qdrant = qdrant

    campana = ejecutar_campana(d)
    reproceso = ejecutar_reproceso(d)

    publicadas = bd.ofertas_laborales.count_documents({})
    assert campana["base_conocimiento"]["estado"] == "actualizada"
    assert reproceso["base_conocimiento"]["estado"] == "actualizada"
    assert qdrant.count("ofertas_pruebas", exact=True).count == publicadas


def test_sin_qdrant_la_base_queda_omitida(respx_mock, dep, params_bc):
    simular_portales(respx_mock, params_bc)
    assert ejecutar_campana(dep(params=params_bc))["base_conocimiento"] == {"estado": "omitida"}
