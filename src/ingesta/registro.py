"""Registro de ejecución (Anexo J §9): colección `ejecuciones` y archivo de registro.

Al no haber un servicio que archive las corridas, estos dos son la evidencia de cada campaña
(medio de verificación de R 2.3).
"""

import logging
import os
import socket
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from ingesta.procesamiento import Resultado

_FORMATO = "%(asctime)s %(levelname)s %(name)s %(message)s"
log = logging.getLogger("ingesta.registro")


def tasa_exito(obtenidos: int, fallidos: int) -> float:
    total = obtenidos + fallidos
    return 1.0 if total == 0 else round(obtenidos / total, 4)


def estado_corrida(
    tasas: dict[str, float], robots_permitido: bool, minimo: float
) -> tuple[str, list[str]]:
    motivos = []
    if not robots_permitido:
        motivos.append(
            "robots.txt prohíbe una ruta vigilada o no se pudo leer: la campaña no arrancó"
        )
    for fuente, tasa in tasas.items():
        if tasa < minimo:
            motivos.append(
                f"{fuente}: tasa de éxito {round(tasa * 100)} % < {round(minimo * 100)} %"
            )
    return ("fallida" if motivos else "exitosa"), motivos


class Acumulador:
    """Resultados del procesamiento de una corrida."""

    def __init__(self):
        self.publicados = 0
        self.competencias = 0
        self.descartes: Counter[str] = Counter(
            {m: 0 for m in ("no_TI", "duplicado", "sin_competencias", "esquema")}
        )
        self.candidatos = 0
        self.contactos = 0

    def sumar(self, r: Resultado) -> None:
        if r.destino == "publicado":
            self.publicados += 1
            self.competencias += r.competencias
        else:
            self.descartes[r.motivo] += 1
        self.candidatos += r.candidatos_nuevos

    def como_documento(self) -> dict:
        return {
            "publicados": self.publicados,
            "descartes": dict(self.descartes),
            "competencias_por_aviso": round(self.competencias / self.publicados, 2)
            if self.publicados
            else 0,
            "candidatos_encolados": self.candidatos,
            "contactos_eliminados": self.contactos,
        }


def abrir_ejecucion(dep, modo: str, inicio: datetime, ruta_log: Path, **extra) -> dict[str, Any]:
    """Documento `en_curso` en `ejecuciones`, con los parámetros, el vocabulario y el modelo."""
    documento = {
        **extra,
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "modo": modo,
        "inicio": inicio,
        "estado": "en_curso",
        "parametros": dep.params.model_dump(),
        "vocabulario": {"version": dep.vocab.version, "terminos": len(dep.vocab.terminos)},
        "modelo_embeddings": dep.modelo,
        "archivo_registro": str(ruta_log),
    }
    documento["_id"] = dep.bd.ejecuciones.insert_one(documento).inserted_id
    log.info("inicio de %s (vocabulario v%s)", modo, dep.vocab.version)
    return documento


def cerrar_ejecucion(
    dep, ejecucion: dict[str, Any], estado: str, motivos: list[str], resultados: dict, **extra
) -> dict[str, Any]:
    fin = dep.ahora()
    cambios = {
        "fin": fin,
        "duracion_s": round((fin - ejecucion["inicio"]).total_seconds(), 1),
        "estado": estado,
        "motivos": motivos,
        "resultados": resultados,
        **extra,
    }
    dep.bd.ejecuciones.update_one({"_id": ejecucion["_id"]}, {"$set": cambios})
    log.info("fin: %s %s %s", estado, motivos, resultados)
    return {**ejecucion, **cambios}


@contextmanager
def bitacora(carpeta: Path, modo: str, inicio: datetime):
    """Adjunta un archivo de registro al logger `ingesta` durante la corrida."""
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"{modo}_{inicio:%Y-%m-%d_%H%M%S}.log"
    manejador = logging.FileHandler(ruta, encoding="utf-8")
    manejador.setFormatter(logging.Formatter(_FORMATO))
    registro = logging.getLogger("ingesta")
    nivel_anterior = registro.level
    registro.setLevel(logging.INFO)
    registro.addHandler(manejador)
    try:
        yield ruta
    finally:
        registro.removeHandler(manejador)
        registro.setLevel(nivel_anterior)
        manejador.close()
