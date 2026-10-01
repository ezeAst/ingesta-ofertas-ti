"""Bumeran: interfaz de datos POST /api/avisos/searchV2 (Anexo I, evidencia V2).

El aviso llega completo en la búsqueda, así que no hay solicitud de detalle. La interfaz no
trae la URL pública: se toma del mapa de sitio (decisión I2) o, si falta, se arma con el patrón.
"""

import re
from collections.abc import Iterator

from ingesta.cliente_http import ClienteHTTP
from ingesta.config import ParamsBumeran
from ingesta.deduplicacion import normalizar
from ingesta.fuentes import AvisoObtenido, FalloAviso

_RE_LOC = re.compile(r"<loc>([^<]+)</loc>")
_RE_ID_URL = re.compile(r"-(\d+)\.html$")


class FuenteBumeran:
    portal = "Bumeran"

    def __init__(self, cliente: ClienteHTTP, params: ParamsBumeran):
        self._c = cliente
        self._p = params
        self.vistos = 0
        self.urls_por_patron = 0

    def listar(self, conocidos: set[str]) -> Iterator[AvisoObtenido | FalloAviso]:
        urls = self._mapa_de_urls()
        p = self._p
        pagina = 0
        while True:
            respuesta = self._c.post(
                f"{p.url_busqueda}?pageSize={p.tamano_pagina}&page={pagina}&sort={p.orden}",
                headers=p.cabeceras,
                json={"filtros": p.filtros},
            )
            if respuesta is None:
                yield FalloAviso(self.portal, f"página {pagina}", "pagina_no_obtenida")
                return
            datos = respuesta.json()
            avisos = datos.get("content") or []
            for aviso in avisos:
                self.vistos += 1
                id_aviso = str(aviso["id"])
                if id_aviso in conocidos:
                    continue
                url = urls.get(id_aviso)
                if url is None:
                    url = self._url_por_patron(aviso)
                    self.urls_por_patron += 1
                yield AvisoObtenido(self.portal, id_aviso, url, aviso)
            pagina += 1
            if not avisos or pagina * p.tamano_pagina >= datos.get("total", 0):
                return

    def _mapa_de_urls(self) -> dict[str, str]:
        respuesta = self._c.get(self._p.url_sitemap)
        if respuesta is None:
            return {}
        return {
            m.group(1): url
            for url in _RE_LOC.findall(respuesta.text)
            if (m := _RE_ID_URL.search(url))
        }

    def _url_por_patron(self, aviso: dict) -> str:
        slug = normalizar(aviso.get("titulo", "")).replace(" ", "-")
        return f"{self._p.url_empleos}{slug}-{aviso['id']}.html"
