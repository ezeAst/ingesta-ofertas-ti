"""CP-03, CP-06, CP-10 y CP-11: el cliente HTTP aplica el protocolo de R 2.1."""

from itertools import pairwise

import httpx
import pytest
import respx

from ingesta.cliente_http import ClienteHTTP, FuenteDetenida

from .utiles import RelojFalso

URL = "https://portal.test/aviso"


@pytest.fixture
def reloj():
    return RelojFalso()


@pytest.fixture
def cliente(params, reloj):
    c = ClienteHTTP(params.http, reloj=reloj, dormir=reloj.dormir)
    yield c
    c.cerrar()


@respx.mock
def test_cp06_espera_minima_entre_solicitudes(cliente, reloj):
    instantes = []
    respx.get(URL).mock(side_effect=lambda req: instantes.append(reloj()) or httpx.Response(200))
    for _ in range(20):
        cliente.get(URL)
    separaciones = [b - a for a, b in pairwise(instantes)]
    assert len(instantes) == 20
    assert min(separaciones) >= 2.0


@respx.mock
def test_cp03_user_agent_de_navegador_sin_credenciales_ni_cookies(cliente, params):
    ruta = respx.get(URL).mock(
        side_effect=[
            httpx.Response(200, headers={"Set-Cookie": "sesion=abc; Path=/"}),
            httpx.Response(200),
        ]
    )
    cliente.get(URL)
    cliente.get(URL)
    for llamada in ruta.calls:
        cabeceras = llamada.request.headers
        assert cabeceras["User-Agent"] == params.http.user_agent
        assert "authorization" not in cabeceras
        assert "cookie" not in cabeceras


@respx.mock
def test_cp10_reintenta_tres_veces_con_espera_creciente(cliente, reloj):
    respx.get(URL).mock(side_effect=[httpx.Response(503)] * 3 + [httpx.Response(200)])
    respuesta = cliente.get(URL)
    assert respuesta is not None and respuesta.status_code == 200
    assert reloj.pausas == [2, 4, 8]
    assert cliente.contadores.fallos == 0


@respx.mock
def test_cp10_agotados_los_reintentos_cuenta_un_fallo(cliente):
    respx.get(URL).mock(side_effect=[httpx.Response(503)] * 4)
    assert cliente.get(URL) is None
    assert cliente.contadores.fallos == 1


@respx.mock
def test_cp10_error_de_red_tambien_se_reintenta(cliente):
    respx.get(URL).mock(side_effect=[httpx.ConnectTimeout("lento"), httpx.Response(200)])
    assert cliente.get(URL).status_code == 200


@respx.mock
def test_cp11_tres_rechazos_seguidos_detienen_la_fuente(cliente):
    respx.get(URL).mock(return_value=httpx.Response(403))
    assert cliente.get(URL) is None
    assert cliente.get(URL) is None
    with pytest.raises(FuenteDetenida, match="3 rechazos consecutivos"):
        cliente.get(URL)
    with pytest.raises(FuenteDetenida):
        cliente.get(URL)  # detenida: no vuelve a consultar
    assert respx.calls.call_count == 3


@respx.mock
def test_cp11_diez_rechazos_acumulados_detienen_la_fuente(cliente):
    respuestas = [httpx.Response(429), httpx.Response(200)] * 9 + [httpx.Response(429)]
    respx.get(URL).mock(side_effect=respuestas)
    for _ in range(18):
        cliente.get(URL)
    with pytest.raises(FuenteDetenida, match="10 rechazos acumulados"):
        cliente.get(URL)
    assert cliente.contadores.rechazos == 10


@respx.mock
def test_un_404_no_se_reintenta(cliente):
    respx.get(URL).mock(return_value=httpx.Response(404))
    assert cliente.get(URL) is None
    assert respx.calls.call_count == 1
