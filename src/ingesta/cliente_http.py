"""Cliente HTTP de una fuente, con el protocolo de R 2.1 incorporado.

- Una solicitud a la vez y al menos `espera_minima_s` desde la anterior (compromiso 4).
- User-Agent de navegador (compromiso 5), sin credenciales y sin conservar cookies (compromiso 2).
- Fallos de red y 5xx: reintentos con espera creciente (2, 4 y 8 s).
- Rechazos (403, 429): no se reintentan; con 3 seguidos o 10 acumulados la fuente se detiene (R5).
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from ingesta.config import ParamsHTTP

RECHAZOS = {403, 429}


class FuenteDetenida(Exception):
    """La fuente alcanzó el corte por rechazos; la campaña sigue con la otra."""


@dataclass
class Contadores:
    solicitudes: int = 0
    fallos: int = 0
    rechazos: int = 0
    rechazos_consecutivos: int = 0
    motivo_corte: str | None = None


class ClienteHTTP:
    def __init__(
        self,
        params: ParamsHTTP,
        *,
        reloj: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], None] = time.sleep,
        bitacora: logging.Logger | None = None,
    ):
        self._p = params
        self._reloj = reloj
        self._dormir = dormir
        self._log = bitacora or logging.getLogger("ingesta.http")
        self._http = httpx.Client(
            headers={"User-Agent": params.user_agent},
            timeout=params.tiempo_limite_s,
            follow_redirects=True,
        )
        self._ultima: float | None = None
        self.contadores = Contadores()

    def get(self, url: str, **opciones) -> httpx.Response | None:
        return self._solicitar("GET", url, **opciones)

    def post(self, url: str, **opciones) -> httpx.Response | None:
        return self._solicitar("POST", url, **opciones)

    def cerrar(self) -> None:
        self._http.close()

    def _solicitar(self, metodo: str, url: str, **opciones) -> httpx.Response | None:
        if self.contadores.motivo_corte:
            raise FuenteDetenida(self.contadores.motivo_corte)
        for intento in range(self._p.reintentos + 1):
            self._esperar_turno()
            respuesta: httpx.Response | None = None
            try:
                respuesta = self._http.request(metodo, url, **opciones)
                estado: int | str = respuesta.status_code
            except httpx.TransportError as error:
                estado = type(error).__name__
            finally:
                self._ultima = self._reloj()
                self._http.cookies.clear()
            self.contadores.solicitudes += 1
            self._log.info("%s %s -> %s", metodo, url, estado)

            if respuesta is not None and respuesta.status_code in RECHAZOS:
                self._registrar_rechazo()
                return None
            if respuesta is not None and respuesta.status_code < 400:
                self.contadores.rechazos_consecutivos = 0
                return respuesta
            reintentable = respuesta is None or respuesta.status_code >= 500
            if reintentable and intento < self._p.reintentos:
                self._dormir(self._p.esperas_reintento_s[intento])
                continue
            self.contadores.fallos += 1
            return None
        return None  # inalcanzable: el último intento siempre retorna

    def _esperar_turno(self) -> None:
        if self._ultima is None:
            return
        transcurrido = self._reloj() - self._ultima
        if transcurrido < self._p.espera_minima_s:
            self._dormir(self._p.espera_minima_s - transcurrido)

    def _registrar_rechazo(self) -> None:
        c = self.contadores
        c.rechazos += 1
        c.rechazos_consecutivos += 1
        if c.rechazos_consecutivos >= self._p.corte_rechazos_consecutivos:
            c.motivo_corte = f"{c.rechazos_consecutivos} rechazos consecutivos"
        elif c.rechazos >= self._p.corte_rechazos_acumulados:
            c.motivo_corte = f"{c.rechazos} rechazos acumulados"
        if c.motivo_corte:
            self._log.warning("fuente detenida: %s", c.motivo_corte)
            raise FuenteDetenida(c.motivo_corte)
