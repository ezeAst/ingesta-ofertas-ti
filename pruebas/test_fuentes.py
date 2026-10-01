"""CP-04, CP-05, CP-12, CP-13 y CP-14: clientes de fuente sobre respuestas simuladas."""

import json

import httpx
import pytest
import respx

from ingesta.cliente_http import ClienteHTTP
from ingesta.fuentes import AvisoObtenido, FalloAviso
from ingesta.fuentes.bumeran import FuenteBumeran
from ingesta.fuentes.computrabajo import FuenteComputrabajo

from .utiles import (
    RelojFalso,
    detalle_computrabajo,
    item_bumeran,
    jobposting,
    listado_computrabajo,
    pagina_bumeran,
)

SITEMAP = (
    '<?xml version="1.0"?><urlset>'
    "<url><loc>https://www.bumeran.com.pe/empleos/analista-programador-acme-s.a.c.-1.html</loc></url>"
    "</urlset>"
)
BASE_CT = "https://pe.computrabajo.com"
ID_1 = "37CCC0A667E1DE6061373E686DCF3405"
ID_2 = "97C9967CF9A0F30C61373E686DCF3405"
RUTA_1 = f"/ofertas-de-trabajo/oferta-de-trabajo-de-desarrollador-java-en-lima-{ID_1}"
RUTA_2 = f"/ofertas-de-trabajo/oferta-de-trabajo-de-analista-en-surco-{ID_2}"


@pytest.fixture
def cliente(params):
    reloj = RelojFalso()
    return ClienteHTTP(params.http, reloj=reloj, dormir=reloj.dormir)


def _bumeran_simulado(params, paginas):
    b = params.fuentes.bumeran
    respx.get(b.url_sitemap).mock(return_value=httpx.Response(200, text=SITEMAP))
    return respx.post(url__startswith=b.url_busqueda).mock(
        side_effect=[httpx.Response(200, json=p) for p in paginas]
    )


@respx.mock
def test_cp12_recorre_todas_las_paginas_con_el_filtro_de_area(cliente, params):
    paginas = [
        pagina_bumeran([item_bumeran(i) for i in range(1, 21)], total=45, numero=0),
        pagina_bumeran([item_bumeran(i) for i in range(21, 41)], total=45, numero=1),
        pagina_bumeran([item_bumeran(i) for i in range(41, 46)], total=45, numero=2),
    ]
    ruta = _bumeran_simulado(params, paginas)
    avisos = list(FuenteBumeran(cliente, params.fuentes.bumeran).listar(conocidos=set()))
    assert len(avisos) == 45
    assert all(isinstance(a, AvisoObtenido) and a.portal == "Bumeran" for a in avisos)
    assert avisos[0].id_aviso == "1"
    cuerpo = json.loads(ruta.calls[0].request.content)
    assert cuerpo == {"filtros": params.fuentes.bumeran.filtros}
    assert ruta.calls[0].request.headers["x-site-id"] == "BMPE"
    assert "page=2" in str(ruta.calls[2].request.url)


@respx.mock
def test_cp12_omite_los_avisos_ya_conocidos(cliente, params):
    _bumeran_simulado(params, [pagina_bumeran([item_bumeran(1), item_bumeran(2)], total=2)])
    fuente = FuenteBumeran(cliente, params.fuentes.bumeran)
    avisos = list(fuente.listar(conocidos={"1"}))
    assert [a.id_aviso for a in avisos] == ["2"]
    assert fuente.vistos == 2


@respx.mock
def test_cp13_url_desde_el_mapa_de_sitio_o_por_patron(cliente, params):
    _bumeran_simulado(
        params, [pagina_bumeran([item_bumeran(1), item_bumeran(7, "Líder Técnico .NET")], total=2)]
    )
    fuente = FuenteBumeran(cliente, params.fuentes.bumeran)
    a1, a7 = list(fuente.listar(conocidos=set()))
    assert a1.url == "https://www.bumeran.com.pe/empleos/analista-programador-acme-s.a.c.-1.html"
    assert a7.url == "https://www.bumeran.com.pe/empleos/lider-tecnico-net-7.html"
    assert fuente.urls_por_patron == 1


def _computrabajo_simulado(params, listado, detalles):
    ct = params.fuentes.computrabajo
    respx.get(ct.url_listado).mock(return_value=httpx.Response(200, text=listado))
    respx.get(f"{ct.url_listado}?p=2").mock(
        return_value=httpx.Response(200, text=listado)
    )  # repite: fin
    for ruta, html in detalles.items():
        respx.get(BASE_CT + ruta).mock(return_value=httpx.Response(200, text=html))


@respx.mock
def test_cp04_el_contenido_sale_del_jobposting_y_no_del_html_visible(cliente, params):
    jp = jobposting(descripcion="Descripción del JSON-LD con Java")
    _computrabajo_simulado(
        params,
        listado_computrabajo([(ID_1, RUTA_1)]),
        {RUTA_1: detalle_computrabajo(jp, visible="TEXTO VISIBLE DISTINTO")},
    )
    (aviso,) = list(
        FuenteComputrabajo(cliente, params.fuentes.computrabajo).listar(conocidos=set())
    )
    assert aviso.contenido == {"jobposting": jp}
    assert "TEXTO VISIBLE" not in json.dumps(aviso.contenido)
    assert aviso.id_aviso == ID_1 and aviso.url == BASE_CT + RUTA_1


@respx.mock
def test_cp05_sin_jobposting_es_fallido_y_no_se_lee_el_html(cliente, params):
    _computrabajo_simulado(
        params, listado_computrabajo([(ID_1, RUTA_1)]), {RUTA_1: detalle_computrabajo(None)}
    )
    (resultado,) = list(
        FuenteComputrabajo(cliente, params.fuentes.computrabajo).listar(conocidos=set())
    )
    assert isinstance(resultado, FalloAviso) and resultado.motivo == "sin_jobposting"


@respx.mock
def test_cp14_url_sin_identificador_es_fallida(cliente, params):
    ruta_truncada = "/ofertas-de-trabajo/oferta-de-trabajo-de-asesor-planilla-completa-firma&"
    _computrabajo_simulado(params, listado_computrabajo([("", ruta_truncada)]), {})
    (resultado,) = list(
        FuenteComputrabajo(cliente, params.fuentes.computrabajo).listar(conocidos=set())
    )
    assert isinstance(resultado, FalloAviso) and resultado.motivo == "id_no_reconocido"
    assert not any(
        "asesor" in str(c.request.url) for c in respx.calls
    )  # ni siquiera se pide el detalle


@respx.mock
def test_computrabajo_no_descarga_el_detalle_de_avisos_conocidos(cliente, params):
    _computrabajo_simulado(
        params,
        listado_computrabajo([(ID_1, RUTA_1), (ID_2, RUTA_2)]),
        {RUTA_2: detalle_computrabajo(jobposting())},
    )
    fuente = FuenteComputrabajo(cliente, params.fuentes.computrabajo)
    avisos = list(fuente.listar(conocidos={ID_1}))
    assert [a.id_aviso for a in avisos] == [ID_2]
    assert fuente.vistos == 2
    assert not any(RUTA_1 in str(c.request.url) for c in respx.calls)
