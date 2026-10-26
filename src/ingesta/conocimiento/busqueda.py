"""Búsqueda en la base de conocimiento (V7, V8, V9, V13 y V18).

1) MongoDB aplica los filtros exactos y devuelve los ids; 2) Qdrant ordena por relevancia dentro
de esos ids, con los tres vectores fusionados por RRF (o uno solo con `via`); 3) MongoDB entrega
las ofertas elegidas y las competencias se cuentan en código. El asistente (R 3) interpreta la
pregunta y redacta; aquí no interviene ningún LLM.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
from pymongo.database import Database
from qdrant_client import QdrantClient, models

from ingesta.config import ParamsBaseConocimiento
from ingesta.conocimiento.sincronizacion import EmbebedorConTokens
from ingesta.conocimiento.textos import VECTORES, id_punto


@dataclass(frozen=True)
class Filtros:
    """Dentro de un campo basta un valor (salvo `competencias`: las pide todas); entre campos,
    se exigen todos. `niveles` solo se aplica si se pide (V8: falta en la mayoría)."""

    competencias: tuple[str, ...] = ()
    categorias: tuple[str, ...] = ()
    tipos: tuple[str, ...] = ()
    niveles: tuple[str, ...] = ()
    portales: tuple[str, ...] = ()
    desde: datetime | None = None
    hasta: datetime | None = None

    def vacio(self) -> bool:
        return not any(
            (self.competencias, self.categorias, self.tipos, self.niveles, self.portales)
        ) and (self.desde is None and self.hasta is None)

    def consulta_mongo(self) -> dict[str, Any]:
        consulta: dict[str, Any] = {}
        if self.competencias:
            consulta["competencias.nombre"] = {"$all": list(self.competencias)}
        if self.categorias:
            consulta["competencias.categoria"] = {"$in": list(self.categorias)}
        if self.tipos:
            consulta["competencias.tipo"] = {"$in": list(self.tipos)}
        if self.niveles:
            condicion: dict[str, Any] = {"nivel_requerido": {"$in": list(self.niveles)}}
            if self.competencias:
                condicion["nombre"] = {"$in": list(self.competencias)}
            consulta["competencias"] = {"$elemMatch": condicion}
        if self.portales:
            consulta["fuente.portal"] = {"$in": list(self.portales)}
        fechas = {op: valor for op, valor in (("$gte", self.desde), ("$lte", self.hasta)) if valor}
        if fechas:
            consulta["fecha_publicacion"] = fechas
        return consulta


@dataclass(frozen=True)
class OfertaEncontrada:
    portal: str
    id_aviso: str
    titulo: str
    empresa: str
    url: str
    fecha_publicacion: datetime | None
    puntaje: float
    fragmento: str
    competencias: list[str]


@dataclass(frozen=True)
class ResultadoBusqueda:
    ofertas: list[OfertaEncontrada]
    conteo: list[tuple[str, int]]
    suficiente: bool
    via: str
    filtradas: int | None


def buscar(
    bd: Database,
    cliente: QdrantClient,
    embebedor: EmbebedorConTokens,
    p: ParamsBaseConocimiento,
    consulta: str,
    filtros: Filtros | None = None,
    via: str | None = None,
) -> ResultadoBusqueda:
    if not consulta.strip():
        raise ValueError("la consulta está vacía")
    if via is not None and via not in VECTORES:
        raise ValueError(f"vía desconocida: {via!r}; opciones: {', '.join(VECTORES)}")
    nombre_via = via or "rrf"

    filtro_qdrant, filtradas = None, None
    if filtros is not None and not filtros.vacio():
        ids = [
            id_punto(o["fuente"]["portal"], o["fuente"]["id_aviso"])
            for o in bd.ofertas_laborales.find(filtros.consulta_mongo(), {"fuente": 1})
        ]
        filtradas = len(ids)
        if not ids:  # una lista vacía en has_id no puede llegar a Qdrant
            return ResultadoBusqueda([], [], False, nombre_via, 0)
        filtro_qdrant = models.Filter(must=[models.HasIdCondition(has_id=ids)])

    vector = embebedor.vectorizar([f"{p.prefijo_consulta}{consulta}"])[0]
    comunes = {
        "limit": p.limite,
        "with_payload": True,
        "with_vectors": ["fragmentos"],
    }
    if via is not None:
        puntos = cliente.query_points(
            p.coleccion,
            query=vector.tolist(),
            using=via,
            query_filter=filtro_qdrant,
            score_threshold=p.umbral_relevancia[via] or None,
            **comunes,
        ).points
    else:
        puntos = cliente.query_points(
            p.coleccion,
            prefetch=[
                models.Prefetch(
                    query=vector.tolist(),
                    using=v,
                    filter=filtro_qdrant,
                    limit=p.limite,
                    score_threshold=p.umbral_relevancia[v] or None,
                )
                for v in VECTORES
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            **comunes,
        ).points

    ofertas = _ofertas(bd, puntos, vector)
    conteo = Counter(n for o in ofertas for n in o.competencias)
    return ResultadoBusqueda(
        ofertas=ofertas,
        conteo=sorted(conteo.items(), key=lambda par: (-par[1], par[0])),
        suficiente=len(ofertas) >= p.minimo_ofertas,
        via=nombre_via,
        filtradas=filtradas,
    )


def _ofertas(bd: Database, puntos: list, vector: np.ndarray) -> list[OfertaEncontrada]:
    """Datos de MongoDB en el orden de Qdrant, con el fragmento más parecido a la consulta."""
    claves = [(p.payload["portal"], p.payload["id_aviso"]) for p in puntos]
    documentos = (
        {
            (o["fuente"]["portal"], o["fuente"]["id_aviso"]): o
            for o in bd.ofertas_laborales.find(
                {"$or": [{"fuente.portal": a, "fuente.id_aviso": b} for a, b in claves]}
            )
        }
        if claves
        else {}
    )
    resultado = []
    for punto, clave in zip(puntos, claves, strict=True):
        oferta = documentos.get(clave)
        if oferta is None:  # borrada en MongoDB después de la última sincronización
            continue
        similitudes = np.asarray(punto.vector["fragmentos"]) @ vector
        resultado.append(
            OfertaEncontrada(
                portal=clave[0],
                id_aviso=clave[1],
                titulo=oferta["titulo"],
                empresa=oferta["empresa"]["nombre"],
                url=oferta["fuente"]["url"],
                fecha_publicacion=oferta.get("fecha_publicacion"),
                puntaje=punto.score,
                fragmento=punto.payload["fragmentos"][int(np.argmax(similitudes))],
                competencias=[c["nombre"] for c in oferta["competencias"]],
            )
        )
    return resultado
