"""Funciones de gestión que usa el panel: corridas por portal, trazas y acciones sobre avisos."""

import os
from datetime import UTC, datetime

import pytest

from ingesta.campana import ejecutar_campana, ejecutar_reproceso
from ingesta.gestion import (
    corrida_en_curso,
    publicar_manual,
    quitar_decision_manual,
    reprocesar_aviso,
)
from ingesta.vocabulario import (
    Vocabulario,
    agregar_categoria,
    agregar_termino,
    agregar_variante,
    guardar_version,
)

from .test_campana import LUNES, VOCAB_PRUEBA, _estado, simular_portales
from .utiles import item_bumeran

pytestmark = [pytest.mark.integracion, pytest.mark.respx(assert_all_called=False)]


def _hosts(respx_mock) -> set[str]:
    return {c.request.url.host for c in respx_mock.calls}


def test_correr_solo_bumeran_no_toca_computrabajo(respx_mock, bd, dep, params_bow):
    simular_portales(respx_mock, params_bow)
    ejecucion = ejecutar_campana(dep(), portales=["Bumeran"])
    assert _hosts(respx_mock) == {"www.bumeran.com.pe"}
    assert set(ejecucion["fuentes"]) == {"Bumeran"}
    assert ejecucion["portales"] == ["Bumeran"]
    assert [r["url"] for r in ejecucion["robots"]] == [params_bow.fuentes.bumeran.robots]


def test_limite_de_avisos_nuevos_por_portal(respx_mock, bd, dep, params_bow):
    simular_portales(respx_mock, params_bow)
    ejecucion = ejecutar_campana(dep(), portales=["Bumeran"], limite=2)
    assert ejecucion["fuentes"]["Bumeran"]["nuevos"] == 2
    assert bd.avisos_crudos.count_documents({}) == 2
    assert ejecucion["limite"] == 2


def test_dia_cualquiera_permite_correr_un_lunes(respx_mock, bd, dep, params_bow):
    simular_portales(respx_mock, params_bow)
    libre = params_bow.model_copy(
        update={"campana": params_bow.campana.model_copy(update={"dia_permitido": "cualquiera"})}
    )
    assert ejecutar_campana(dep(ahora=LUNES, params=libre))["estado"] == "exitosa"


def test_la_traza_registra_como_entro_y_como_quedo(respx_mock, bd, dep, params_bow):
    simular_portales(respx_mock, params_bow)
    ejecutar_campana(dep())
    traza = bd.trazas.find_one({"portal": "Bumeran", "id_aviso": "1"})
    assert traza["destino"] == "publicado" and traza["motivo"] is None
    assert traza["unidades"][0] == {"texto": "Desarrollador Python", "seccion": None}
    python = next(c for c in traza["coincidencias"] if c["termino"] == "Python")
    assert python["via"] == "literal" and "unidad" in python and "texto" in python
    assert traza["version_vocabulario"] == 1
    no_ti = bd.trazas.find_one({"portal": "Bumeran", "id_aviso": "2"})
    assert no_ti["destino"] == "descartado" and no_ti["motivo"] == "no_TI"


def test_reprocesar_un_aviso_con_el_vocabulario_nuevo(respx_mock, bd, dep, params_bow, tmp_path):
    simular_portales(
        respx_mock,
        params_bow,
        bumeran=[
            item_bumeran(6, "DevOps", detalle="Experiencia en Terraform y Docker"),
            item_bumeran(7, "Asesor", detalle="Atención al cliente"),
        ],
    )
    carpeta = tmp_path / "vocabulario"
    guardar_version(VOCAB_PRUEBA, carpeta)
    ejecutar_campana(dep(vocab=Vocabulario.cargar_vigente(carpeta)))
    assert _estado(bd, "Bumeran", "6") == "no_TI"
    nuevo = agregar_variante(
        VOCAB_PRUEBA, "Infraestructura como código", "Terraform", descriptiva=False
    )
    guardar_version(nuevo, carpeta)
    llamadas = respx_mock.calls.call_count
    resultado = reprocesar_aviso(dep(vocab=Vocabulario.cargar_vigente(carpeta)), "Bumeran", "6")
    assert resultado.destino == "publicado"
    assert _estado(bd, "Bumeran", "6") == "publicado"
    assert bd.trazas.find_one({"id_aviso": "6"})["version_vocabulario"] == 2
    assert bd.trazas.find_one({"id_aviso": "7"})["version_vocabulario"] == 1  # no se tocó
    assert respx_mock.calls.call_count == llamadas


def test_publicacion_manual_sobrevive_al_reproceso(respx_mock, bd, dep, params_bow):
    simular_portales(respx_mock, params_bow)
    ejecutar_campana(dep())
    assert _estado(bd, "Bumeran", "2") == "no_TI"
    publicar_manual(dep(), "Bumeran", "2", ["Trabajo en equipo", "Comunicación efectiva"])
    oferta = bd.ofertas_laborales.find_one({"fuente.id_aviso": "2"})
    assert [c["nombre"] for c in oferta["competencias"]] == [
        "Trabajo en equipo",
        "Comunicación efectiva",
    ]
    assert oferta["competencias"][0]["tipo"] == "transversal"
    assert bd.ofertas_descartadas.count_documents({"id_aviso": "2"}) == 0
    assert bd.trazas.find_one({"id_aviso": "2"})["decision_manual"]["accion"] == "publicar"

    ejecutar_reproceso(dep())
    assert _estado(bd, "Bumeran", "2") == "publicado"

    quitar_decision_manual(bd, "Bumeran", "2")
    reprocesar_aviso(dep(), "Bumeran", "2")
    assert _estado(bd, "Bumeran", "2") == "no_TI"


def test_publicacion_manual_exige_terminos_del_vocabulario(respx_mock, bd, dep, params_bow):
    simular_portales(respx_mock, params_bow)
    ejecutar_campana(dep())
    with pytest.raises(ValueError, match="no existe"):
        publicar_manual(dep(), "Bumeran", "2", ["Inventado"])
    with pytest.raises(ValueError, match="al menos una"):
        publicar_manual(dep(), "Bumeran", "2", [])


def test_corrida_en_curso_detecta_procesos_vivos_y_muertos(bd):
    vivo = bd.ejecuciones.insert_one(
        {
            "modo": "campana",
            "estado": "en_curso",
            "inicio": datetime.now(UTC),
            "pid": os.getpid(),
            "host": os.uname().nodename,
        }
    ).inserted_id
    assert corrida_en_curso(bd)["_id"] == vivo
    bd.ejecuciones.update_one({"_id": vivo}, {"$set": {"pid": 999_999}})
    assert corrida_en_curso(bd) is None
    assert bd.ejecuciones.find_one({"_id": vivo})["estado"] == "interrumpida"


def test_agregar_categoria_nueva_y_un_termino_en_ella():
    datos = agregar_categoria(VOCAB_PRUEBA, "Observabilidad y monitoreo", "técnica")
    datos = agregar_termino(datos, "Dynatrace", "Observabilidad y monitoreo")
    vocab = Vocabulario(datos)
    assert vocab.rama("Observabilidad y monitoreo") == "técnica"
    assert vocab.termino("Dynatrace")["categoria"] == "Observabilidad y monitoreo"
    with pytest.raises(ValueError, match="rama"):
        agregar_categoria(VOCAB_PRUEBA, "Otra", "blanda")
    with pytest.raises(ValueError, match="ya existe"):
        agregar_categoria(VOCAB_PRUEBA, "Bases de datos", "técnica")
