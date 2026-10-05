"""Conexión a MongoDB y preparación idempotente de las colecciones (Anexo J §7)."""

from typing import Any

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.database import Database

from ingesta.config import Entorno

COLECCIONES = (
    "avisos_crudos",
    "ofertas_laborales",
    "ofertas_descartadas",
    "candidatos_competencia",
    "lexicos_rechazados",
    "ejecuciones",
    "trazas",
)


def conectar(entorno: Entorno, nombre_bd: str | None = None) -> Database:
    cliente: MongoClient = MongoClient(
        entorno.mongo_uri, tz_aware=True, serverSelectionTimeoutMS=5000
    )
    return cliente[nombre_bd or entorno.mongo_bd]


def preparar(bd: Database, esquema: dict[str, Any]) -> None:
    """Crea las colecciones, el validador $jsonSchema de R 1.4 y los índices. Se puede repetir."""
    existentes = set(bd.list_collection_names())
    opciones = {"validator": esquema, "validationLevel": "strict", "validationAction": "error"}
    if "ofertas_laborales" in existentes:
        bd.command("collMod", "ofertas_laborales", **opciones)
    else:
        bd.create_collection("ofertas_laborales", **opciones)
    for nombre in COLECCIONES:
        if nombre not in existentes and nombre != "ofertas_laborales":
            bd.create_collection(nombre)

    par = [("portal", ASCENDING), ("id_aviso", ASCENDING)]
    bd.ofertas_laborales.create_index(
        [("fuente.portal", ASCENDING), ("fuente.id_aviso", ASCENDING)],
        unique=True,
        name="portal_id_aviso",
    )
    bd.avisos_crudos.create_index(par, unique=True, name="portal_id_aviso")
    bd.avisos_crudos.create_index([("fecha_extraccion", ASCENDING)])
    bd.ofertas_descartadas.create_index(par, unique=True, name="portal_id_aviso")
    bd.ofertas_descartadas.create_index([("motivo", ASCENDING)])
    bd.candidatos_competencia.create_index(
        [*par, ("tramo", ASCENDING)], unique=True, name="portal_id_aviso_tramo"
    )
    bd.candidatos_competencia.create_index([("estado", ASCENDING)])
    bd.candidatos_competencia.create_index([("origen", ASCENDING), ("clave", ASCENDING)])
    bd.lexicos_rechazados.create_index([("clave", ASCENDING)], unique=True, name="clave")
    bd.ejecuciones.create_index([("inicio", DESCENDING)])
    bd.trazas.create_index(par, unique=True, name="portal_id_aviso")
    bd.trazas.create_index([("destino", ASCENDING), ("motivo", ASCENDING)])
