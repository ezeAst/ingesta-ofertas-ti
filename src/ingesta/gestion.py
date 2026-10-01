"""Acciones de gestión sobre avisos individuales y control de corridas (las usa el panel)."""

import os
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pymongo.database import Database

from ingesta.almacen import Trazas
from ingesta.campana import Dependencias, _dedup_desde_bd, _procesador
from ingesta.procesamiento import Resultado

# Una corrida iniciada desde otro contenedor no se puede comprobar por su PID; pasado este
# plazo sin cerrarse, se da por interrumpida.
_PLAZO_CORRIDA_AJENA = timedelta(hours=12)


def reprocesar_aviso(dep: Dependencias, portal: str, id_aviso: str) -> Resultado:
    """Vuelve a pasar un aviso por el flujo con el vocabulario vigente, sin usar la red."""
    crudo = dep.bd.avisos_crudos.find_one({"portal": portal, "id_aviso": id_aviso})
    if crudo is None:
        raise ValueError(f"no hay crudo para {portal} {id_aviso}")
    return _procesador(dep, _dedup_desde_bd(dep)).procesar(crudo)


def publicar_manual(dep: Dependencias, portal: str, id_aviso: str, nombres: list[str]) -> Resultado:
    """Publica un aviso con las competencias que elige el revisor.

    La decisión queda en la traza y se respeta en cada reproceso, hasta que se quite. Las
    competencias deben existir en el vocabulario: el esquema de R 1.4 no admite términos libres.
    """
    if not nombres:
        raise ValueError("indica al menos una competencia")
    extraidas = {
        c["nombre"]: c
        for c in (dep.bd.trazas.find_one({"portal": portal, "id_aviso": id_aviso}) or {}).get(
            "competencias", []
        )
    }
    competencias = []
    for nombre in nombres:
        try:
            termino = dep.vocab.termino(nombre)
        except KeyError:
            raise ValueError(
                f"el término {nombre!r} no existe en el vocabulario v{dep.vocab.version}"
            ) from None
        competencia = {
            "nombre": nombre,
            "categoria": termino["categoria"],
            "tipo": dep.vocab.rama(termino["categoria"]),
        }
        if nivel := extraidas.get(nombre, {}).get("nivel_requerido"):
            competencia["nivel_requerido"] = nivel
        competencias.append(competencia)

    trazas = Trazas(dep.bd)
    trazas.fijar_decision_manual(
        portal,
        id_aviso,
        {"accion": "publicar", "competencias": competencias, "fecha": dep.ahora()},
    )
    resultado = reprocesar_aviso(dep, portal, id_aviso)
    if resultado.destino != "publicado":
        trazas.fijar_decision_manual(portal, id_aviso, None)
        detalle = dep.bd.ofertas_descartadas.find_one({"portal": portal, "id_aviso": id_aviso})
        raise ValueError(
            f"el validador de R 1.4 rechazó la oferta: {(detalle or {}).get('detalle')}"
        )
    return resultado


def quitar_decision_manual(bd: Database, portal: str, id_aviso: str) -> None:
    """El aviso vuelve a decidirse por las reglas en el próximo reproceso."""
    Trazas(bd).fijar_decision_manual(portal, id_aviso, None)


def corrida_en_curso(bd: Database) -> dict[str, Any] | None:
    """Ejecución abierta cuyo proceso sigue vivo; las abandonadas se marcan «interrumpida»."""
    ahora = datetime.now(UTC)
    for corrida in bd.ejecuciones.find({"estado": "en_curso"}).sort("inicio", -1):
        propia = corrida.get("host") == socket.gethostname()
        vencida = ahora - corrida["inicio"] > _PLAZO_CORRIDA_AJENA
        if (propia and not _vivo(corrida.get("pid"))) or (not propia and vencida):
            bd.ejecuciones.update_one(
                {"_id": corrida["_id"]},
                {
                    "$set": {
                        "estado": "interrumpida",
                        "fin": ahora,
                        "motivos": ["el proceso terminó sin cerrar la ejecución"],
                    }
                },
            )
            continue
        return corrida
    return None


def _vivo(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    estado = Path(f"/proc/{pid}/stat")
    if estado.exists():  # un proceso zombi ya terminó aunque todavía tenga PID
        return estado.read_text().split(")")[-1].split()[0] != "Z"
    return True
