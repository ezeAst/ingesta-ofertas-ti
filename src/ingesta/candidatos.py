"""Revisión humana de la cola de candidatos (Anexo J §13, «aparece un término nuevo»).

Aprobar un candidato crea una versión nueva del vocabulario; el reproceso del crudo la aplica a
los avisos ya ingresados sin volver a consultar los portales.

Los candidatos de la vía léxica se revisan por tramo, no por aviso: aprobar o rechazar uno
resuelve todos los pendientes con el mismo tramo, y el rechazo vale también para avisos futuros.

Las decisiones también se toman en lote: se exporta la cola a CSV o Excel, se completa la columna
`decision` y se importa el archivo. Todas las aprobaciones del lote generan una sola versión del
vocabulario.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.database import Database

from ingesta.vocabulario import (
    RAMAS,
    Vocabulario,
    agregar_termino,
    agregar_variante,
    guardar_version,
)

DECISIONES = ("variante", "nueva", "rechazar")


def _pendiente(bd: Database, id_candidato: ObjectId | str) -> dict:
    candidato = bd.candidatos_competencia.find_one({"_id": ObjectId(id_candidato)})
    if candidato is None:
        raise ValueError(f"no existe el candidato {id_candidato}")
    if candidato["estado"] != "pendiente":
        raise ValueError(f"el candidato {id_candidato} ya fue revisado ({candidato['estado']})")
    return candidato


def _mismo_tramo(candidato: dict) -> dict:
    """Filtro de los pendientes que se resuelven junto con este candidato."""
    if candidato.get("origen") == "lexico":
        return {"origen": "lexico", "clave": candidato["clave"], "estado": "pendiente"}
    return {"_id": candidato["_id"]}


def _con_tramo(
    datos: dict[str, Any],
    candidato: dict,
    *,
    termino: str | None = None,
    nuevo_termino: str | None = None,
    categoria: str | None = None,
    descriptiva: bool = False,
) -> tuple[dict[str, Any], str]:
    """Vocabulario con el tramo añadido y el término al que quedó asignado."""
    tramo = candidato["tramo"]
    if nuevo_termino:
        if not categoria:
            raise ValueError("un término nuevo necesita su categoría de R 1.2")
        datos = agregar_termino(datos, nuevo_termino, categoria)
        if tramo != nuevo_termino:
            datos = agregar_variante(datos, nuevo_termino, tramo, descriptiva=descriptiva)
        return datos, nuevo_termino
    if termino:
        return agregar_variante(datos, termino, tramo, descriptiva=descriptiva), termino
    raise ValueError("indicar el término existente o el término nuevo")


def _marcar_aprobado(bd: Database, candidato: dict, destino: str, version: int) -> None:
    bd.candidatos_competencia.update_many(
        _mismo_tramo(candidato),
        {
            "$set": {
                "estado": "aprobado",
                "termino_asignado": destino,
                "resuelto": datetime.now(UTC),
                "version_vocabulario_nueva": version,
            }
        },
    )


def _marcar_rechazado(bd: Database, candidato: dict) -> None:
    ahora = datetime.now(UTC)
    bd.candidatos_competencia.update_many(
        _mismo_tramo(candidato), {"$set": {"estado": "rechazado", "resuelto": ahora}}
    )
    if candidato.get("origen") == "lexico":
        bd.lexicos_rechazados.update_one(
            {"clave": candidato["clave"]},
            {"$setOnInsert": {"tramo": candidato["tramo"], "creado": ahora}},
            upsert=True,
        )


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
    datos, destino = _con_tramo(
        Vocabulario.cargar_vigente(carpeta_vocabulario).datos,
        candidato,
        termino=termino,
        nuevo_termino=nuevo_termino,
        categoria=categoria,
        descriptiva=descriptiva,
    )
    ruta = guardar_version(datos, carpeta_vocabulario)
    version = Vocabulario.cargar_vigente(carpeta_vocabulario).version
    _marcar_aprobado(bd, candidato, destino, version)
    return ruta


def rechazar(bd: Database, id_candidato: ObjectId | str) -> None:
    _marcar_rechazado(bd, _pendiente(bd, id_candidato))


# --- Decisiones en lote (CSV o Excel) -------------------------------------------------------


@dataclass
class FilaImportada:
    fila: int  # número de fila en el archivo (la 1 es la cabecera)
    id: str
    tramo: str
    decision: str
    estado: str  # «ok», «error» u «omitida»
    detalle: str


@dataclass
class Importacion:
    filas: list[FilaImportada] = field(default_factory=list)
    version: Path | None = None  # versión del vocabulario creada al aplicar, si hubo aprobaciones

    def cuantas(self, estado: str) -> int:
        return sum(f.estado == estado for f in self.filas)


def _si_no(valor: str) -> bool:
    valor = valor.lower()
    if valor in ("", "no", "n", "false", "0"):
        return False
    if valor in ("si", "sí", "s", "true", "1", "x"):
        return True
    raise ValueError(f"«descriptiva» debe ser si o no, no {valor!r}")


def _decidir(datos: dict[str, Any], candidato: dict, decision: str, f: dict[str, str]):
    """(vocabulario, término asignado o None si se rechaza, detalle). ValueError si no vale."""
    if decision == "rechazar":
        return datos, None, "se rechaza"
    if decision == "variante":
        descriptiva = _si_no(f.get("descriptiva", ""))
        datos, destino = _con_tramo(
            datos, candidato, termino=f.get("termino") or None, descriptiva=descriptiva
        )
        tipo = "descriptiva" if descriptiva else "literal"
        return datos, destino, f"variante {tipo} de «{destino}»"
    if decision == "nueva":
        nombre = f.get("nuevo_termino") or candidato["tramo"]
        if any(t["nombre"] == nombre for t in datos["terminos"]):
            if candidato["tramo"] != nombre:
                datos = agregar_variante(datos, nombre, candidato["tramo"], descriptiva=False)
            return datos, nombre, f"«{nombre}» ya existe: el tramo queda como su variante"
        categoria = f.get("categoria", "")
        if not categoria:
            raise ValueError("una habilidad nueva necesita su categoría")
        if categoria not in set(datos["categorias"]) | set(RAMAS):
            raise ValueError(f"categoría desconocida: {categoria!r}")
        datos, _ = _con_tramo(datos, candidato, nuevo_termino=nombre, categoria=categoria)
        return datos, nombre, f"habilidad nueva «{nombre}» en {categoria}"
    raise ValueError(f"decisión desconocida {decision!r}: usar {', '.join(DECISIONES)} o vacío")


def _anotar(resultado: Importacion, *datos_fila: Any) -> None:
    resultado.filas.append(FilaImportada(*datos_fila))


def importar_decisiones(
    bd: Database, filas: list[dict[str, Any]], carpeta_vocabulario: Path, *, aplicar: bool
) -> Importacion:
    """Valida las decisiones del archivo y, con `aplicar`, ejecuta las válidas.

    Columnas: `id`, `decision` (variante, nueva, rechazar o vacía), `termino`, `descriptiva`,
    `nuevo_termino` y `categoria`. Las filas sin decisión no se tocan; un candidato ya revisado
    se omite. Una habilidad nueva que ya existe (en el vocabulario o creada antes en el mismo
    archivo) recibe el tramo como variante.
    """
    datos = Vocabulario.cargar_vigente(carpeta_vocabulario).datos
    resultado = Importacion()
    aprobados: list[tuple[dict, str]] = []
    rechazados: list[dict] = []
    vistos: set[Any] = set()

    for numero, fila in enumerate(filas, start=2):
        f = {
            str(k).strip().lower(): "" if v is None else str(v).strip()
            for k, v in fila.items()
            if k is not None
        }
        decision = f.get("decision", "").lower()
        if not decision:
            continue
        try:
            candidato = bd.candidatos_competencia.find_one({"_id": ObjectId(f.get("id", ""))})
        except (InvalidId, TypeError):
            candidato = None
        tramo = candidato["tramo"] if candidato else f.get("tramo", "")

        anotar = partial(_anotar, resultado, numero, f.get("id", ""), tramo, decision)
        if candidato is None:
            anotar("error", "no existe un candidato con ese id")
            continue
        es_lexico = candidato.get("origen") == "lexico"
        grupo = ("lexico", candidato["clave"]) if es_lexico else candidato["_id"]
        if grupo in vistos:
            anotar("error", "el candidato aparece dos veces en el archivo")
            continue
        if candidato["estado"] != "pendiente":
            anotar("omitida", f"ya fue revisado ({candidato['estado']})")
            continue
        try:
            datos, destino, detalle = _decidir(datos, candidato, decision, f)
        except ValueError as error:
            anotar("error", str(error))
            continue
        vistos.add(grupo)
        if destino is None:
            rechazados.append(candidato)
        else:
            aprobados.append((candidato, destino))
        anotar("ok", detalle)

    if aplicar:
        if aprobados:
            resultado.version = guardar_version(datos, carpeta_vocabulario)
            version = Vocabulario.cargar_vigente(carpeta_vocabulario).version
            for candidato, destino in aprobados:
                _marcar_aprobado(bd, candidato, destino, version)
        for candidato in rechazados:
            _marcar_rechazado(bd, candidato)
    return resultado
