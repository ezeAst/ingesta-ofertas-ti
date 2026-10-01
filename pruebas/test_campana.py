"""Pruebas de integración de la campaña y el reproceso contra MongoDB (base `ingesta_pruebas`).

Los portales se simulan con respx y el modelo de embeddings con el embebedor de palabras;
MongoDB es real, con el validador $jsonSchema de R 1.4.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from ingesta.almacen import Destinos, EsquemaInvalido
from ingesta.campana import CampanaFueraDeDia, ejecutar_campana, ejecutar_reproceso
from ingesta.candidatos import aprobar
from ingesta.vocabulario import Vocabulario, guardar_version

from .utiles import (
    VOCAB_PRUEBA,
    detalle_computrabajo,
    item_bumeran,
    jobposting,
    listado_computrabajo,
    pagina_bumeran,
)

pytestmark = [pytest.mark.integracion, pytest.mark.respx(assert_all_called=False)]

DOMINGO = datetime(2026, 9, 27, 15, 0, tzinfo=UTC)  # 10:00 en Lima
LUNES = datetime(2026, 9, 28, 15, 0, tzinfo=UTC)
ROBOTS_OK = "User-agent: *\nDisallow: /postulantes/\n"
BASE_CT = "https://pe.computrabajo.com"

DESC_PYTHON = "Experiencia con Python y SQL Server.  Manejo de Git  Buen ambiente laboral"
ITEMS_BUMERAN = [
    item_bumeran(1, "Desarrollador Python", detalle=DESC_PYTHON),
    item_bumeran(2, "Asesor comercial", detalle="Atención al cliente.  Trabajo en equipo"),
    item_bumeran(
        3,
        "Programador Backend",
        empresa="Confidencial",
        confidencial=True,
        detalle="Python y Docker avanzado.  Enviar CV a juan.perez@correo.com o al 987654321",
    ),
    item_bumeran(4, "Especialista", detalle="Infraestructura en la nube"),
    item_bumeran(
        5,
        "Desarrollador Go",
        detalle="Python y Docker",
        fechaHoraPublicacion="ayer",
        fechaPublicacion=None,
    ),
]


def _ruta(n: int, hexa: str) -> str:
    return f"/ofertas-de-trabajo/oferta-de-trabajo-de-aviso-{n}-en-lima-{hexa}"


HEX = {n: f"{n:02d}" + "A" * 30 for n in range(1, 4)}
AVISOS_CT = {
    # 1: el mismo aviso que Bumeran 1, publicado en el otro portal (duplicado).
    _ruta(1, HEX[1]): detalle_computrabajo(
        jobposting("Desarrollador Python", DESC_PYTHON.replace("  ", "<br>"))
    ),
    _ruta(2, HEX[2]): detalle_computrabajo(
        jobposting("Analista de Datos", "Python, R y SQL<br>Pensamiento analítico")
    ),
    _ruta(3, HEX[3]): detalle_computrabajo(None),  # sin JobPosting: fallido
}


def simular_portales(
    router, params, *, bumeran=ITEMS_BUMERAN, estado_bumeran=200, robots=ROBOTS_OK
):
    b, ct = params.fuentes.bumeran, params.fuentes.computrabajo
    router.get(b.robots).mock(return_value=httpx.Response(200, text=robots))
    router.get(ct.robots).mock(return_value=httpx.Response(200, text=robots))
    if estado_bumeran == 200:
        router.get(b.url_sitemap).mock(return_value=httpx.Response(200, text="<urlset></urlset>"))
        router.post(url__startswith=b.url_busqueda).mock(
            return_value=httpx.Response(200, json=pagina_bumeran(bumeran, total=len(bumeran)))
        )
    else:
        router.get(b.url_sitemap).mock(return_value=httpx.Response(estado_bumeran))
        router.post(url__startswith=b.url_busqueda).mock(
            return_value=httpx.Response(estado_bumeran)
        )
    listado = listado_computrabajo([(ruta.rsplit("-", 1)[1], ruta) for ruta in AVISOS_CT])
    router.get(ct.url_listado).mock(return_value=httpx.Response(200, text=listado))
    router.get(f"{ct.url_listado}?p=2").mock(return_value=httpx.Response(200, text=listado))
    for ruta, html in AVISOS_CT.items():
        router.get(BASE_CT + ruta).mock(return_value=httpx.Response(200, text=html))


def _estado(bd, portal, id_aviso):
    if bd.ofertas_laborales.find_one({"fuente.portal": portal, "fuente.id_aviso": id_aviso}):
        return "publicado"
    d = bd.ofertas_descartadas.find_one({"portal": portal, "id_aviso": id_aviso})
    return d["motivo"] if d else None


def test_cp37_campana_normal_de_punta_a_punta(respx_mock, bd, dep, params_bow):
    simular_portales(respx_mock, params_bow)
    ejecucion = ejecutar_campana(dep())
    assert _estado(bd, "Bumeran", "1") == "publicado"
    assert _estado(bd, "Bumeran", "2") == "no_TI"
    assert _estado(bd, "Bumeran", "3") == "publicado"
    assert _estado(bd, "Bumeran", "4") == "sin_competencias"
    assert _estado(bd, "Bumeran", "5") == "esquema"
    assert _estado(bd, "Computrabajo", HEX[1]) == "duplicado"
    assert _estado(bd, "Computrabajo", HEX[2]) == "publicado"
    assert ejecucion["estado"] == "exitosa"
    ct = ejecucion["fuentes"]["Computrabajo"]
    assert ct["fallidos"] == 1 and ct["motivos_fallo"] == {"sin_jobposting": 1}
    assert ejecucion["resultados"]["descartes"] == {
        "no_TI": 1,
        "duplicado": 1,
        "sin_competencias": 1,
        "esquema": 1,
    }


def test_cp31_repetir_la_campana_no_escribe_nada_nuevo(respx_mock, bd, dep, params_bow):
    simular_portales(respx_mock, params_bow)
    ejecutar_campana(dep())
    antes = {
        c: bd[c].count_documents({})
        for c in ("avisos_crudos", "ofertas_laborales", "ofertas_descartadas")
    }
    segunda = ejecutar_campana(dep())
    despues = {c: bd[c].count_documents({}) for c in antes}
    assert antes == despues
    assert segunda["fuentes"]["Bumeran"]["nuevos"] == 0
    indices = bd.ofertas_laborales.index_information().values()
    assert any(
        i.get("unique") and i["key"] == [("fuente.portal", 1), ("fuente.id_aviso", 1)]
        for i in indices
    )


def test_cp08_los_contactos_no_llegan_a_ninguna_coleccion(respx_mock, bd, dep, params_bow):
    simular_portales(respx_mock, params_bow)
    ejecutar_campana(dep())
    for coleccion in (
        "avisos_crudos",
        "ofertas_laborales",
        "ofertas_descartadas",
        "candidatos_competencia",
    ):
        volcado = json.dumps(list(bd[coleccion].find({}, {"_id": 0})), default=str)
        assert "juan.perez" not in volcado and "987654321" not in volcado


def test_cp15_el_crudo_conserva_el_original_sin_html_de_pagina(respx_mock, bd, dep, params_bow):
    simular_portales(respx_mock, params_bow)
    ejecutar_campana(dep())
    crudo = bd.avisos_crudos.find_one({"portal": "Computrabajo", "id_aviso": HEX[2]})
    assert set(crudo) >= {"portal", "id_aviso", "url", "contenido", "fecha_extraccion", "huella"}
    assert crudo["contenido"]["jobposting"]["title"] == "Analista de Datos"
    assert "<html" not in json.dumps(crudo["contenido"])
    bumeran = bd.avisos_crudos.find_one({"portal": "Bumeran", "id_aviso": "1"})
    assert bumeran["contenido"]["titulo"] == "Desarrollador Python"


def test_cp26_y_cp30_sin_competencias_y_confidencial(respx_mock, bd, dep, params_bow):
    simular_portales(respx_mock, params_bow)
    ejecutar_campana(dep())
    descartado = bd.ofertas_descartadas.find_one({"portal": "Bumeran", "id_aviso": "4"})
    assert descartado["detalle"]["tramos_encolados"]
    assert bd.candidatos_competencia.count_documents({"portal": "Bumeran", "id_aviso": "4"}) >= 1
    oferta = bd.ofertas_laborales.find_one({"fuente.id_aviso": "3"})
    assert oferta["empresa"]["nombre"] == "Confidencial"
    assert {c["nombre"] for c in oferta["competencias"]} == {"Python", "Docker"}
    docker = next(c for c in oferta["competencias"] if c["nombre"] == "Docker")
    assert docker["nivel_requerido"] == "avanzado"


def test_cp29_el_validador_rechaza_una_oferta_incompleta(bd):
    with pytest.raises(EsquemaInvalido):
        Destinos(bd).publicar(
            {
                "titulo": "Sin fecha",
                "descripcion": "x",
                "fuente": {
                    "portal": "Bumeran",
                    "id_aviso": "9",
                    "url": "u",
                    "fecha_extraccion": DOMINGO,
                },
                "empresa": {"nombre": "ACME"},
                "competencias": [
                    {
                        "nombre": "Python",
                        "categoria": "Lenguajes de programación",
                        "tipo": "técnica",
                    }
                ],
            }
        )


def test_cp38_una_fuente_caida_no_detiene_a_la_otra(respx_mock, bd, dep, params_bow):
    simular_portales(respx_mock, params_bow, estado_bumeran=403)
    ejecucion = ejecutar_campana(dep())
    assert ejecucion["estado"] == "fallida"
    assert any("Bumeran" in m for m in ejecucion["motivos"])
    assert ejecucion["fuentes"]["Computrabajo"]["nuevos"] == 2
    assert _estado(bd, "Computrabajo", HEX[2]) == "publicado"


def test_cp02_robots_prohibido_no_consulta_los_portales(respx_mock, bd, dep, params_bow):
    simular_portales(respx_mock, params_bow, robots="User-agent: *\nDisallow: /api/avisos/\n")
    ejecucion = ejecutar_campana(dep())
    assert ejecucion["estado"] == "fallida"
    assert all(c.request.url.path.endswith("robots.txt") for c in respx_mock.calls)
    assert bd.avisos_crudos.count_documents({}) == 0


def test_cp07_campana_fuera_del_dia_se_rechaza_y_el_reproceso_no(respx_mock, bd, dep, params_bow):
    """Con `dia_permitido = "domingo"`, una campaña del lunes se rechaza sin tocar la red."""
    simular_portales(respx_mock, params_bow)
    solo_domingo = params_bow.model_copy(
        update={"campana": params_bow.campana.model_copy(update={"dia_permitido": "domingo"})}
    )
    with pytest.raises(CampanaFueraDeDia):
        ejecutar_campana(dep(ahora=LUNES, params=solo_domingo))
    assert respx_mock.calls.call_count == 0
    assert ejecutar_reproceso(dep(ahora=LUNES, params=solo_domingo))["estado"] == "exitosa"


def test_cp33_el_reproceso_mueve_avisos_en_ambos_sentidos_sin_red(respx_mock, bd, dep, params_bow):
    simular_portales(respx_mock, params_bow)
    ejecutar_campana(dep())
    llamadas = respx_mock.calls.call_count
    exigente = params_bow.model_copy(
        update={
            "filtro_ti": params_bow.filtro_ti.model_copy(update={"minimo_competencias_tecnicas": 3})
        }
    )
    ejecutar_reproceso(dep(params=exigente))
    assert _estado(bd, "Bumeran", "3") == "no_TI"  # Python y Docker: 2 < 3
    assert _estado(bd, "Bumeran", "1") == "publicado"  # Python, SQL Server y Git
    ejecutar_reproceso(dep())
    assert _estado(bd, "Bumeran", "3") == "publicado"
    assert bd.ofertas_descartadas.count_documents({"id_aviso": "3"}) == 0
    assert respx_mock.calls.call_count == llamadas  # el reproceso no usa la red


def test_cp34_candidato_aprobado_se_recupera_en_el_reproceso(
    respx_mock, bd, dep, params_bow, tmp_path
):
    item = item_bumeran(6, "DevOps", detalle="Experiencia en Terraform y Docker")
    simular_portales(respx_mock, params_bow, bumeran=[item])
    carpeta = tmp_path / "vocabulario"
    guardar_version(VOCAB_PRUEBA, carpeta)
    ejecutar_campana(dep(vocab=Vocabulario.cargar_vigente(carpeta)))
    assert _estado(bd, "Bumeran", "6") == "no_TI"  # solo Docker es técnica literal

    candidato = bd.candidatos_competencia.insert_one(
        {
            "portal": "Bumeran",
            "id_aviso": "6",
            "tramo": "Terraform",
            "unidad": "Experiencia en Terraform y Docker",
            "termino_cercano": "Infraestructura como código",
            "puntaje": 0.7,
            "estado": "pendiente",
        }
    ).inserted_id
    aprobar(bd, candidato, carpeta, termino="Infraestructura como código")
    vocab = Vocabulario.cargar_vigente(carpeta)
    assert (
        vocab.version == 2
        and "Terraform" in vocab.termino("Infraestructura como código")["literales"]
    )
    assert bd.candidatos_competencia.find_one({"_id": candidato})["estado"] == "aprobado"

    ejecutar_reproceso(dep(vocab=vocab))
    oferta = bd.ofertas_laborales.find_one({"fuente.id_aviso": "6"})
    assert {c["nombre"] for c in oferta["competencias"]} == {
        "Infraestructura como código",
        "Docker",
    }


def test_cp35_la_ejecucion_queda_registrada_con_sus_metricas(respx_mock, bd, dep, params_bow):
    simular_portales(respx_mock, params_bow)
    ejecucion = ejecutar_campana(dep())
    guardada = bd.ejecuciones.find_one({"_id": ejecucion["_id"]})
    for clave in (
        "modo",
        "inicio",
        "fin",
        "duracion_s",
        "estado",
        "parametros",
        "vocabulario",
        "modelo_embeddings",
        "robots",
        "fuentes",
        "resultados",
        "archivo_registro",
    ):
        assert clave in guardada, clave
    for clave in ("vistos", "nuevos", "fallidos", "solicitudes", "rechazos", "tasa_exito"):
        assert clave in guardada["fuentes"]["Bumeran"], clave
    r = guardada["resultados"]
    assert (
        r["publicados"] == 3 and r["candidatos_encolados"] >= 1 and r["contactos_eliminados"] == 2
    )
    assert r["competencias_por_aviso"] > 0
    assert guardada["parametros"]["http"]["espera_minima_s"] == 2.0
    registro = Path(guardada["archivo_registro"]).read_text(encoding="utf-8")
    assert "POST https://www.bumeran.com.pe/api/avisos/searchV2" in registro


def test_via_semantica_apagada_no_usa_embeddings(respx_mock, bd, dep, params_bow):
    simular_portales(respx_mock, params_bow)
    extraccion = params_bow.extraccion.model_copy(update={"usar_via_semantica": False})
    solo_diccionario = params_bow.model_copy(update={"extraccion": extraccion})
    d = dep(params=solo_diccionario)
    ejecucion = ejecutar_campana(d)
    assert d.embebedor.llamadas == []
    assert bd.candidatos_competencia.count_documents({}) == 0
    assert _estado(bd, "Bumeran", "4") == "sin_competencias"
    assert ejecucion["parametros"]["extraccion"]["usar_via_semantica"] is False
    assert bd.trazas.find_one({"id_aviso": "1"})["via_semantica"] is False
