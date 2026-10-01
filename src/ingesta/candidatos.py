"""Revisión humana de la cola de candidatos (Anexo J §13, «aparece un término nuevo»).

Aprobar un candidato crea una versión nueva del vocabulario; el reproceso del crudo la aplica a
los avisos ya ingresados sin volver a consultar los portales.
"""

from datetime import UTC, datetime
from pathlib import Path

from bson import ObjectId
from pymongo.database import Database

from ingesta.vocabulario import Vocabulario, agregar_termino, agregar_variante, guardar_version


def _pendiente(bd: Database, id_candidato: ObjectId | str) -> dict:
    candidato = bd.candidatos_competencia.find_one({"_id": ObjectId(id_candidato)})
    if candidato is None:
        raise ValueError(f"no existe el candidato {id_candidato}")
    if candidato["estado"] != "pendiente":
        raise ValueError(f"el candidato {id_candidato} ya fue revisado ({candidato['estado']})")
    return candidato


def aprobar(
    bd: Database,
    id_candidato: ObjectId | str,
    carpeta_vocabulario: Path,
    *,
    termino: str | None = None,
    nuevo_termino: str | None = None,
    categoria: str | None = None,
    descriptiva: bool = False,
) -> Path:
    """Añade el tramo como variante de un término existente, o crea un término nuevo."""
    candidato = _pendiente(bd, id_candidato)
    datos = Vocabulario.cargar_vigente(carpeta_vocabulario).datos
    if nuevo_termino:
        if not categoria:
            raise ValueError("un término nuevo necesita su categoría de R 1.2")
        datos = agregar_termino(datos, nuevo_termino, categoria)
        destino = nuevo_termino
        if candidato["tramo"] != nuevo_termino:
            datos = agregar_variante(
                datos, nuevo_termino, candidato["tramo"], descriptiva=descriptiva
            )
    elif termino:
        datos = agregar_variante(datos, termino, candidato["tramo"], descriptiva=descriptiva)
        destino = termino
    else:
        raise ValueError("indicar el término existente o el término nuevo")
    ruta = guardar_version(datos, carpeta_vocabulario)
    version = Vocabulario.cargar_vigente(carpeta_vocabulario).version
    bd.candidatos_competencia.update_one(
        {"_id": candidato["_id"]},
        {
            "$set": {
                "estado": "aprobado",
                "termino_asignado": destino,
                "resuelto": datetime.now(UTC),
                "version_vocabulario_nueva": version,
            }
        },
    )
    return ruta


def rechazar(bd: Database, id_candidato: ObjectId | str) -> None:
    candidato = _pendiente(bd, id_candidato)
    bd.candidatos_competencia.update_one(
        {"_id": candidato["_id"]}, {"$set": {"estado": "rechazado", "resuelto": datetime.now(UTC)}}
    )
