"""Repositorio de crudo, destinos (publicado o descartado) y cola de candidatos.

Corresponden a las colecciones del Anexo J §7 y a los componentes de §5.
"""

import hashlib
import json
from datetime import datetime
from typing import Any

from pymongo import ASCENDING
from pymongo.database import Database
from pymongo.errors import WriteError

from ingesta.extraccion import Candidato
from ingesta.fuentes import AvisoObtenido
from ingesta.privacidad import limpiar_estructura

MOTIVOS = ("no_TI", "duplicado", "sin_competencias", "esquema")
_VALIDACION_FALLIDA = 121  # DocumentValidationFailure


class EsquemaInvalido(Exception):
    """El validador $jsonSchema de R 1.4 rechazó la oferta."""


class RepositorioCrudo:
    def __init__(self, bd: Database):
        self._c = bd.avisos_crudos

    def conocidos(self, portal: str) -> set[str]:
        return {d["id_aviso"] for d in self._c.find({"portal": portal}, {"id_aviso": 1})}

    def guardar(self, aviso: AvisoObtenido, fecha: datetime) -> dict[str, Any]:
        """Guarda el original sin datos de contacto (I12), antes de cualquier transformación.
        Si el aviso ya estaba, no se sobrescribe: el crudo es el registro de lo recolectado."""
        contenido, contactos = limpiar_estructura(aviso.contenido)
        huella = hashlib.sha256(
            json.dumps(contenido, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        clave = {"portal": aviso.portal, "id_aviso": aviso.id_aviso}
        documento = {
            **clave,
            "url": aviso.url,
            "contenido": contenido,
            "fecha_extraccion": fecha,
            "huella": huella,
            "contactos_eliminados": contactos,
        }
        self._c.update_one(clave, {"$setOnInsert": documento}, upsert=True)
        return self._c.find_one(clave)

    def todos(self):
        return self._c.find().sort([("fecha_extraccion", ASCENDING), ("_id", ASCENDING)])


class Destinos:
    """Cada aviso está en un solo destino: publicado o descartado con motivo (I7)."""

    def __init__(self, bd: Database):
        self._ofertas = bd.ofertas_laborales
        self._descartes = bd.ofertas_descartadas

    def publicar(self, oferta: dict[str, Any]) -> None:
        fuente = oferta["fuente"]
        try:
            self._ofertas.replace_one(
                {"fuente.portal": fuente["portal"], "fuente.id_aviso": fuente["id_aviso"]},
                oferta,
                upsert=True,
            )
        except WriteError as error:
            if error.code == _VALIDACION_FALLIDA:
                detalle = (error.details or {}).get("errInfo", error.details)
                raise EsquemaInvalido(
                    json.dumps(detalle, default=str, ensure_ascii=False)
                ) from error
            raise
        self._descartes.delete_one({"portal": fuente["portal"], "id_aviso": fuente["id_aviso"]})

    def descartar(
        self, portal: str, id_aviso: str, motivo: str, detalle: dict[str, Any], fecha: datetime
    ) -> None:
        if motivo not in MOTIVOS:
            raise ValueError(f"motivo de descarte desconocido: {motivo}")
        clave = {"portal": portal, "id_aviso": id_aviso}
        self._descartes.replace_one(
            clave, {**clave, "motivo": motivo, "detalle": detalle, "fecha": fecha}, upsert=True
        )
        self._ofertas.delete_one({"fuente.portal": portal, "fuente.id_aviso": id_aviso})


class ColaCandidatos:
    def __init__(self, bd: Database):
        self._c = bd.candidatos_competencia
        # Un tramo léxico rechazado se descarta para todo el corpus, no solo para su aviso.
        self._rechazados = {d["clave"] for d in bd.lexicos_rechazados.find({}, {"clave": 1})}

    def encolar(
        self,
        portal: str,
        id_aviso: str,
        candidato: Candidato,
        version_vocabulario: int,
        fecha: datetime,
    ) -> bool:
        """Encola un tramo dudoso; devuelve True si es nuevo. Un tramo ya revisado no se reabre."""
        clave = candidato.tramo.lower()
        if candidato.origen == "lexico" and clave in self._rechazados:
            return False
        resultado = self._c.update_one(
            {"portal": portal, "id_aviso": id_aviso, "tramo": candidato.tramo},
            {
                "$setOnInsert": {"estado": "pendiente", "creado": fecha},
                "$set": {
                    "unidad": candidato.unidad,
                    "origen": candidato.origen,
                    "clave": clave,
                    "termino_cercano": candidato.termino_cercano,
                    "puntaje": candidato.puntaje,
                    "version_vocabulario": version_vocabulario,
                },
            },
            upsert=True,
        )
        return resultado.upserted_id is not None


class Trazas:
    """Cómo se procesó cada aviso: unidades, coincidencias, candidatos y destino.

    Es la evidencia que muestra el panel («cómo entró y cómo quedó registrado»). Se reescribe
    en cada reproceso, salvo `decision_manual`, que solo cambia el revisor desde el panel.
    """

    def __init__(self, bd: Database):
        self._c = bd.trazas

    def guardar(self, portal: str, id_aviso: str, traza: dict[str, Any]) -> None:
        self._c.update_one(
            {"portal": portal, "id_aviso": id_aviso},
            {"$set": {"portal": portal, "id_aviso": id_aviso, **traza}},
            upsert=True,
        )

    def decision_manual(self, portal: str, id_aviso: str) -> dict[str, Any] | None:
        traza = self._c.find_one({"portal": portal, "id_aviso": id_aviso}, {"decision_manual": 1})
        return (traza or {}).get("decision_manual")

    def fijar_decision_manual(self, portal: str, id_aviso: str, decision: dict[str, Any] | None):
        cambio = (
            {"$set": {"decision_manual": decision}}
            if decision
            else {"$unset": {"decision_manual": ""}}
        )
        self._c.update_one({"portal": portal, "id_aviso": id_aviso}, cambio, upsert=True)
