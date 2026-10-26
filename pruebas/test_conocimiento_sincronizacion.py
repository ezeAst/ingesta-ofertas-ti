"""BC-05 a BC-09 y BC-22: carga y sincronización de `ofertas_laborales` con Qdrant (R 2.4, V10).

MongoDB y Qdrant son reales (base `ingesta_pruebas`, colección `ofertas_pruebas`); el modelo de
embeddings es el embebedor de palabras.
"""

import pytest

from ingesta.conocimiento import coleccion
from ingesta.conocimiento.sincronizacion import configuracion, sincronizar
from ingesta.conocimiento.textos import huella, id_punto

from .utiles import EmbebedorPalabras, insertar_oferta

pytestmark = pytest.mark.integracion


@pytest.fixture
def entorno(bd, qdrant, params_bc):
    for i, titulo in enumerate(("Analista de Datos", "Desarrollador Backend", "DevOps"), 1):
        insertar_oferta(bd, f"A{i}", titulo=titulo)
    embebedor = EmbebedorPalabras()

    def sync(todo=False, modelo=""):
        return sincronizar(
            bd, qdrant, embebedor, params_bc.base_conocimiento, todo=todo, modelo=modelo
        )

    return bd, qdrant, embebedor, sync


def test_bc05_primera_carga_crea_un_punto_por_oferta(entorno, params_bc):
    _, qdrant, _, sync = entorno
    r = sync()
    assert r["creadas"] == 3
    assert r["puntos"] == 3
    assert r["fragmentos"] >= 3
    assert r["por_portal"] == {"Computrabajo": 3}
    (punto,) = qdrant.retrieve(
        params_bc.base_conocimiento.coleccion, [id_punto("Computrabajo", "A1")], with_vectors=True
    )
    assert set(punto.vector) == {"titulo", "competencias", "fragmentos"}
    assert len(punto.vector["fragmentos"]) >= 1
    assert punto.payload["portal"] == "Computrabajo"
    assert punto.payload["id_aviso"] == "A1"
    assert len(punto.payload["fragmentos"]) == len(punto.vector["fragmentos"])
    assert not punto.payload["fragmentos"][0].startswith("passage: ")


def test_bc06_segunda_sincronizacion_sin_cambios_no_toca_nada(entorno):
    _, _, embebedor, sync = entorno
    sync()
    embebedor.llamadas.clear()
    r = sync()
    assert (r["creadas"], r["actualizadas"], r["borradas"], r["sin_cambios"]) == (0, 0, 0, 3)
    assert embebedor.llamadas == []


def test_bc07_oferta_modificada_se_actualiza(entorno, params_bc):
    bd, qdrant, _, sync = entorno
    sync()
    bd.ofertas_laborales.update_one(
        {"fuente.id_aviso": "A2"},
        {"$set": {"competencias": [{"nombre": "Java", "categoria": "x", "tipo": "técnica"}]}},
    )
    r = sync()
    assert r["actualizadas"] == 1
    assert r["sin_cambios"] == 2
    nueva = bd.ofertas_laborales.find_one({"fuente.id_aviso": "A2"})
    (punto,) = qdrant.retrieve(
        params_bc.base_conocimiento.coleccion, [id_punto("Computrabajo", "A2")]
    )
    assert punto.payload["huella"] == huella(nueva, configuracion(params_bc.base_conocimiento, ""))


def test_bc08_oferta_borrada_sale_de_qdrant(entorno):
    bd, _, _, sync = entorno
    sync()
    bd.ofertas_laborales.delete_one({"fuente.id_aviso": "A3"})
    r = sync()
    assert r["borradas"] == 1
    assert r["puntos"] == 2


def test_bc09_todo_reconstruye_desde_cero(entorno):
    _, _, _, sync = entorno
    sync()
    r = sync(todo=True)
    assert r["creadas"] == 3
    assert r["puntos"] == 3


def test_bc22_cambio_de_modelo_recalcula_todo(entorno):
    _, _, _, sync = entorno
    sync(modelo="e5@a")
    r = sync(modelo="bge-m3@b")
    assert (r["actualizadas"], r["sin_cambios"]) == (3, 0)


def test_bc22_dimension_distinta_pide_reconstruir(entorno, params_bc):
    _, qdrant, _, sync = entorno
    coleccion.asegurar(qdrant, params_bc.base_conocimiento.coleccion, 8)
    with pytest.raises(ValueError, match="--todo"):
        sync()
