"""Conversaciones, turnos y ofertas guardadas de cada usuario.

Cada operación filtra por el id del usuario: nadie puede leer ni borrar lo de otro. Los turnos
guardan una copia de las ofertas recuperadas, así el chat se puede reabrir tal como se vio y
sirve para la evaluación RAG y de sesgos sin repetir llamadas al LLM.
"""

from datetime import UTC, datetime

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import DESCENDING
from pymongo.database import Database

from ingesta.asistente.servicio import Turno
from ingesta.conocimiento.busqueda import OfertaEncontrada

LARGO_TITULO = 60


def _id(valor) -> ObjectId | None:
    try:
        return valor if isinstance(valor, ObjectId) else ObjectId(str(valor))
    except (InvalidId, TypeError):
        return None


def titulo_de(pregunta: str) -> str:
    limpio = " ".join(pregunta.split())
    return limpio if len(limpio) <= LARGO_TITULO else limpio[: LARGO_TITULO - 1].rstrip() + "…"


class Historial:
    def __init__(self, bd: Database):
        self._bd = bd

    # --- conversaciones ---
    def crear(self, usuario_id, primera_pregunta: str) -> ObjectId:
        ahora = datetime.now(UTC)
        return self._bd.conversaciones.insert_one(
            {
                "usuario_id": usuario_id,
                "titulo": titulo_de(primera_pregunta),
                "creada": ahora,
                "actualizada": ahora,
            }
        ).inserted_id

    def listar(self, usuario_id, limite: int = 50) -> list[dict]:
        return list(
            self._bd.conversaciones.find(
                {"usuario_id": usuario_id}, {"titulo": 1, "actualizada": 1}
            )
            .sort("actualizada", DESCENDING)
            .limit(limite)
        )

    def borrar(self, usuario_id, conversacion_id) -> bool:
        cid = _id(conversacion_id)
        borrada = self._bd.conversaciones.delete_one(
            {"_id": cid, "usuario_id": usuario_id}
        ).deleted_count
        if borrada:
            self._bd.turnos.delete_many({"conversacion_id": cid, "usuario_id": usuario_id})
        return bool(borrada)

    # --- turnos ---
    def guardar_turno(self, usuario_id, conversacion_id, turno: Turno) -> None:
        cid = _id(conversacion_id)
        if not self._bd.conversaciones.find_one({"_id": cid, "usuario_id": usuario_id}, {"_id": 1}):
            raise PermissionError("la conversación no es de este usuario")
        orden = self._bd.turnos.count_documents({"conversacion_id": cid})
        ahora = datetime.now(UTC)
        self._bd.turnos.insert_one(
            {
                "conversacion_id": cid,
                "usuario_id": usuario_id,
                "orden": orden,
                "fecha": ahora,
                **turno.a_doc(),
            }
        )
        self._bd.conversaciones.update_one({"_id": cid}, {"$set": {"actualizada": ahora}})

    def turnos(self, usuario_id, conversacion_id) -> list[Turno]:
        cid = _id(conversacion_id)
        return [
            Turno.desde_doc(d)
            for d in self._bd.turnos.find({"conversacion_id": cid, "usuario_id": usuario_id}).sort(
                "orden"
            )
        ]

    # --- ofertas guardadas ---
    def guardar_oferta(self, usuario_id, o: OfertaEncontrada) -> None:
        self._bd.ofertas_guardadas.update_one(
            {"usuario_id": usuario_id, "portal": o.portal, "id_aviso": o.id_aviso},
            {
                "$setOnInsert": {"fecha": datetime.now(UTC)},
                "$set": {
                    "titulo": o.titulo,
                    "empresa": o.empresa,
                    "url": o.url,
                    "fecha_publicacion": o.fecha_publicacion,
                    "competencias": o.competencias,
                },
            },
            upsert=True,
        )

    def quitar_oferta(self, usuario_id, portal: str, id_aviso: str) -> None:
        self._bd.ofertas_guardadas.delete_one(
            {"usuario_id": usuario_id, "portal": portal, "id_aviso": id_aviso}
        )

    def ofertas_guardadas(self, usuario_id) -> list[dict]:
        return list(
            self._bd.ofertas_guardadas.find({"usuario_id": usuario_id}).sort("fecha", DESCENDING)
        )

    def claves_guardadas(self, usuario_id) -> set[tuple[str, str]]:
        return {
            (d["portal"], d["id_aviso"])
            for d in self._bd.ofertas_guardadas.find(
                {"usuario_id": usuario_id}, {"portal": 1, "id_aviso": 1}
            )
        }
