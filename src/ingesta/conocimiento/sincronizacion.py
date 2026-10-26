"""Sincronización de `ofertas_laborales` con Qdrant (V10).

MongoDB es la fuente de verdad: se crean los puntos de las ofertas nuevas, se recalculan los de
las ofertas cuya huella cambió y se borran los que ya no tienen oferta.
"""

from collections import Counter
from typing import Any, Protocol

import numpy as np
from pymongo.database import Database
from qdrant_client import QdrantClient, models

from ingesta.config import ParamsBaseConocimiento
from ingesta.conocimiento import coleccion
from ingesta.conocimiento.textos import (
    fragmentar,
    huella,
    id_punto,
    texto_competencias,
    texto_titulo,
)

LIMITE_MODELO = 512  # TEI recorta lo que pase de aquí
_PROYECCION = {"titulo": 1, "descripcion": 1, "fuente": 1, "competencias.nombre": 1}


class EmbebedorConTokens(Protocol):
    def vectorizar(self, textos: list[str]) -> np.ndarray: ...

    def contar_tokens(self, textos: list[str]) -> list[int]: ...


def configuracion(p: ParamsBaseConocimiento, modelo: str) -> str:
    """Lo que, además del contenido de la oferta, determina sus vectores."""
    return f"{modelo}|{p.prefijo_pasaje}|{p.max_tokens_fragmento}"


def sincronizar(
    bd: Database,
    cliente: QdrantClient,
    embebedor: EmbebedorConTokens,
    p: ParamsBaseConocimiento,
    todo: bool = False,
    modelo: str = "",
) -> dict[str, Any]:
    """`modelo` identifica el modelo de embeddings (nombre y revisión): si cambia, se recalculan
    todas las ofertas en lugar de mezclar vectores de dos modelos."""
    if todo:
        cliente.delete_collection(p.coleccion)
    existia = cliente.collection_exists(p.coleccion)
    if not existia:
        coleccion.asegurar(cliente, p.coleccion, _dimension(embebedor, p))

    config = configuracion(p, modelo)
    ofertas = {}
    for oferta in bd.ofertas_laborales.find({}, _PROYECCION):
        f = oferta["fuente"]
        ofertas[id_punto(f["portal"], f["id_aviso"])] = oferta
    existentes = coleccion.huellas(cliente, p.coleccion)

    pendientes = [i for i, o in ofertas.items() if existentes.get(i) != huella(o, config)]
    if pendientes and existia:
        _verificar_dimension(cliente, embebedor, p)
    sobrantes = [i for i in existentes if i not in ofertas]
    resultado: dict[str, Any] = {
        "creadas": sum(1 for i in pendientes if i not in existentes),
        "actualizadas": sum(1 for i in pendientes if i in existentes),
        "borradas": len(sobrantes),
        "sin_cambios": len(ofertas) - len(pendientes),
        "fragmentos": 0,
        "fragmentos_recortados": 0,
    }
    for inicio in range(0, len(pendientes), p.lote):
        lote = [(i, ofertas[i]) for i in pendientes[inicio : inicio + p.lote]]
        fragmentos, recortados = _cargar_lote(cliente, embebedor, p, lote, config)
        resultado["fragmentos"] += fragmentos
        resultado["fragmentos_recortados"] += recortados
    if sobrantes:
        cliente.delete(p.coleccion, points_selector=models.PointIdsList(points=sobrantes))

    resultado["puntos"] = cliente.count(p.coleccion, exact=True).count
    resultado["por_portal"] = dict(Counter(o["fuente"]["portal"] for o in ofertas.values()))
    return resultado


def _dimension(embebedor: EmbebedorConTokens, p: ParamsBaseConocimiento) -> int:
    return embebedor.vectorizar([f"{p.prefijo_pasaje}x"]).shape[1]


def _verificar_dimension(
    cliente: QdrantClient, embebedor: EmbebedorConTokens, p: ParamsBaseConocimiento
) -> None:
    actual = cliente.get_collection(p.coleccion).config.params.vectors["titulo"].size
    nueva = _dimension(embebedor, p)
    if nueva != actual:
        raise ValueError(
            f"la colección «{p.coleccion}» tiene vectores de {actual} dimensiones y el modelo "
            f"actual da {nueva}: reconstrúyela con `ingesta vectorizar --todo`"
        )


def _cargar_lote(
    cliente: QdrantClient,
    embebedor: EmbebedorConTokens,
    p: ParamsBaseConocimiento,
    lote: list[tuple[str, dict[str, Any]]],
    config: str,
) -> tuple[int, int]:
    """Vectoriza un lote de ofertas en una sola llamada y lo escribe. Devuelve cuántos fragmentos
    se cargaron y cuántos pasan del límite del modelo."""
    textos: list[str] = []
    por_oferta = []
    for _, oferta in lote:
        fragmentos = fragmentar(
            oferta, p.prefijo_pasaje, p.max_tokens_fragmento, embebedor.contar_tokens
        )
        por_oferta.append(fragmentos)
        textos += [
            texto_titulo(oferta, p.prefijo_pasaje),
            texto_competencias(oferta, p.prefijo_pasaje),
            *fragmentos,
        ]
    vectores = embebedor.vectorizar(textos)

    puntos, fila = [], 0
    for (id_, oferta), fragmentos in zip(lote, por_oferta, strict=True):
        n = len(fragmentos)
        puntos.append(
            models.PointStruct(
                id=id_,
                vector={
                    "titulo": vectores[fila].tolist(),
                    "competencias": vectores[fila + 1].tolist(),
                    "fragmentos": vectores[fila + 2 : fila + 2 + n].tolist(),
                },
                payload={
                    "portal": oferta["fuente"]["portal"],
                    "id_aviso": oferta["fuente"]["id_aviso"],
                    "huella": huella(oferta, config),
                    "fragmentos": [f.removeprefix(p.prefijo_pasaje) for f in fragmentos],
                },
            )
        )
        fila += 2 + n
    cliente.upsert(p.coleccion, points=puntos)

    todos = [f for fragmentos in por_oferta for f in fragmentos]
    recortados = sum(1 for t in embebedor.contar_tokens(todos) if t > LIMITE_MODELO)
    return len(todos), recortados
