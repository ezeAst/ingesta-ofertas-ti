"""Corrida de vectorización (V11): sincroniza Qdrant y la deja registrada en `ejecuciones`.

Su documento (creadas, actualizadas, borradas, fragmentos, duración) es la evidencia del
«reporte de registros almacenados» de la Tabla 2.
"""

import logging
from typing import Any

from ingesta.conocimiento.sincronizacion import sincronizar
from ingesta.registro import abrir_ejecucion, bitacora, cerrar_ejecucion

log = logging.getLogger("ingesta.conocimiento")


def ejecutar_vectorizacion(dep, todo: bool = False) -> dict[str, Any]:
    """`dep` es una `campana.Dependencias` con `qdrant`. `todo` reconstruye desde cero."""
    p = dep.params.base_conocimiento
    inicio = dep.ahora()
    with bitacora(dep.dir_logs, "vectorizacion", inicio) as ruta_log:
        ejecucion = abrir_ejecucion(
            dep, "vectorizacion", inicio, ruta_log, coleccion=p.coleccion, todo=todo
        )
        try:
            resultados = sincronizar(dep.bd, dep.qdrant, dep.embebedor, p, todo=todo)
        except Exception as error:
            cerrar_ejecucion(dep, ejecucion, "fallida", [str(error)], {})
            raise
        log.info("Qdrant «%s»: %s", p.coleccion, resultados)
        return cerrar_ejecucion(dep, ejecucion, "exitosa", [], resultados)
