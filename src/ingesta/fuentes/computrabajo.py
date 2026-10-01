"""Computrabajo: listado de la categoría y bloque JSON-LD `JobPosting` de cada aviso.

Del HTML solo se leen los enlaces del listado. El contenido del aviso sale siempre del
`JobPosting` (compromiso 3); una página sin ese bloque cuenta como fallida (decisión I6).
"""

import json
import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from ingesta.cliente_http import ClienteHTTP
from ingesta.config import ParamsComputrabajo
from ingesta.fuentes import AvisoObtenido, FalloAviso

_PREFIJO_AVISO = "/ofertas-de-trabajo/"


class FuenteComputrabajo:
    portal = "Computrabajo"

    def __init__(self, cliente: ClienteHTTP, params: ParamsComputrabajo):
        self._c = cliente
        self._p = params
        partes = urlsplit(params.url_listado)
        self._base = f"{partes.scheme}://{partes.netloc}"
        self._re_id = re.compile(params.patron_id_aviso)
        self.vistos = 0

    def listar(self, conocidos: set[str]) -> Iterator[AvisoObtenido | FalloAviso]:
        vistas: set[str] = set()
        for numero in range(1, self._p.max_paginas + 1):
            url = self._p.url_listado if numero == 1 else f"{self._p.url_listado}?p={numero}"
            respuesta = self._c.get(url)
            if respuesta is None:
                yield FalloAviso(self.portal, url, "pagina_no_obtenida")
                return
            rutas = [r for r in rutas_de_avisos(respuesta.text) if r not in vistas]
            if not rutas:  # página vacía o repetida: fin del listado
                return
            for ruta in rutas:
                vistas.add(ruta)
                self.vistos += 1
                yield from self._aviso(ruta, conocidos)

    def _aviso(self, ruta: str, conocidos: set[str]) -> Iterator[AvisoObtenido | FalloAviso]:
        url = self._base + ruta
        encontrado = self._re_id.search(ruta)
        if encontrado is None:
            yield FalloAviso(self.portal, url, "id_no_reconocido")
            return
        id_aviso = encontrado.group(1)
        if id_aviso in conocidos:
            return
        detalle = self._c.get(url)
        if detalle is None:
            yield FalloAviso(self.portal, url, "detalle_no_obtenido")
            return
        jobposting = extraer_jobposting(detalle.text)
        if jobposting is None:
            yield FalloAviso(self.portal, url, "sin_jobposting")
            return
        yield AvisoObtenido(self.portal, id_aviso, url, {"jobposting": jobposting})


def rutas_de_avisos(html: str) -> list[str]:
    """Rutas de los avisos del listado, en orden y sin el fragmento de seguimiento (#lc=...)."""
    rutas: list[str] = []
    for articulo in BeautifulSoup(html, "lxml").select("article.box_offer"):
        for enlace in articulo.select("a[href]"):
            ruta = (
                urlsplit(enlace["href"]).path
                if enlace["href"].startswith("http")
                else enlace["href"]
            )
            ruta = ruta.split("#")[0]
            if ruta.startswith(_PREFIJO_AVISO):
                if ruta not in rutas:
                    rutas.append(ruta)
                break
    return rutas


def extraer_jobposting(html: str) -> dict[str, Any] | None:
    for bloque in BeautifulSoup(html, "lxml").find_all("script", type="application/ld+json"):
        try:
            encontrado = _buscar(json.loads(bloque.string or bloque.get_text()))
        except json.JSONDecodeError:
            continue
        if encontrado:
            return encontrado
    return None


def _buscar(nodo: Any) -> dict[str, Any] | None:
    if isinstance(nodo, list):
        return next((r for item in nodo if (r := _buscar(item))), None)
    if isinstance(nodo, dict):
        if nodo.get("@type") == "JobPosting":
            return nodo
        return _buscar(list(nodo.values()))
    return None
