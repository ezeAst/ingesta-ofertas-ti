"""CP-01 y CP-02: verificación de robots.txt antes de la campaña (compromiso 1)."""

import httpx
import pytest
import respx

from ingesta.cliente_http import ClienteHTTP
from ingesta.robots import verificar_robots

from .utiles import RelojFalso

ROBOTS = "https://www.bumeran.com.pe/robots.txt"
RUTAS = ["/api/avisos/searchV2", "/sitemap_avisos_bum.xml"]


@pytest.fixture
def cliente(params):
    reloj = RelojFalso()
    return ClienteHTTP(params.http, reloj=reloj, dormir=reloj.dormir)


@respx.mock
def test_cp01_rutas_permitidas_y_huella_registrada(cliente, params):
    respx.get(ROBOTS).mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /postulantes/\n")
    )
    r = verificar_robots(cliente, ROBOTS, RUTAS, params.http.user_agent, huella_anterior=None)
    assert r.permitido and r.prohibidas == []
    assert len(r.huella) == 64 and "Disallow: /postulantes/" in r.texto
    assert r.cambio is False


@respx.mock
def test_cp01_un_cambio_fuera_de_las_rutas_vigiladas_no_detiene(cliente, params):
    respx.get(ROBOTS).mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /nuevo/\n")
    )
    r = verificar_robots(cliente, ROBOTS, RUTAS, params.http.user_agent, huella_anterior="otra")
    assert r.permitido and r.cambio is True


@respx.mock
def test_cp02_una_ruta_vigilada_prohibida_impide_la_campana(cliente, params):
    respx.get(ROBOTS).mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /api/avisos/\n")
    )
    r = verificar_robots(cliente, ROBOTS, RUTAS, params.http.user_agent, huella_anterior=None)
    assert not r.permitido
    assert r.prohibidas == ["/api/avisos/searchV2"]


@respx.mock
def test_sin_robots_legible_no_se_asume_permiso(cliente, params):
    respx.get(ROBOTS).mock(return_value=httpx.Response(503))
    r = verificar_robots(cliente, ROBOTS, RUTAS, params.http.user_agent, huella_anterior=None)
    assert not r.permitido and r.prohibidas == RUTAS
