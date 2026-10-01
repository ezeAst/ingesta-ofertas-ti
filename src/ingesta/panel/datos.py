"""Consultas, resaltado y lanzamiento de corridas para el panel (sin dependencias de Streamlit)."""

import html
import subprocess
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pymongo.database import Database

from ingesta.config import DIR_LOGS, RAIZ

LIMA = ZoneInfo("America/Lima")
ETIQUETA_MOTIVO = {
    "no_TI": "No es de TI",
    "duplicado": "Duplicado",
    "sin_competencias": "Sin competencias",
    "esquema": "Rechazado por el esquema",
}
_procesos: dict[int, subprocess.Popen] = {}  # corridas lanzadas por este panel


def hora_lima(valor: datetime | None) -> str:
    return valor.astimezone(LIMA).strftime("%Y-%m-%d %H:%M") if valor else ""


def lanzar(argumentos: list[str]) -> int:
    """Inicia `ingesta <argumentos>` como proceso aparte; el panel no se bloquea mientras corre."""
    DIR_LOGS.mkdir(parents=True, exist_ok=True)
    salida = DIR_LOGS / f"panel_{datetime.now(LIMA):%Y-%m-%d_%H%M%S}_{'_'.join(argumentos)}.out"
    with salida.open("w", encoding="utf-8") as archivo:
        proceso = subprocess.Popen(
            ["ingesta", *argumentos],
            cwd=RAIZ,
            stdout=archivo,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    _procesos[proceso.pid] = proceso
    return proceso.pid


def recoger_terminados() -> None:
    """Recoge los procesos terminados para que no queden como zombis."""
    for pid, proceso in list(_procesos.items()):
        if proceso.poll() is not None:
            del _procesos[pid]


def ultimas_lineas(ruta: str | Path | None, n: int = 25) -> str:
    if not ruta or not Path(ruta).exists():
        return ""
    with Path(ruta).open(encoding="utf-8", errors="replace") as archivo:
        return "".join(deque(archivo, maxlen=n))


def avisos(
    bd: Database,
    portal: str | None = None,
    destino: str | None = None,
    motivos: list[str] | None = None,
    texto: str = "",
    limite: int = 1000,
) -> list[dict[str, Any]]:
    """Una fila por aviso procesado, desde su traza."""
    filtro: dict[str, Any] = {}
    if portal:
        filtro["portal"] = portal
    if destino:
        filtro["destino"] = destino
    if motivos:
        filtro["motivo"] = {"$in": motivos}
    if texto:
        filtro["titulo"] = {"$regex": _escapar_regex(texto), "$options": "i"}
    proyeccion = {
        "portal": 1,
        "id_aviso": 1,
        "titulo": 1,
        "destino": 1,
        "motivo": 1,
        "fecha": 1,
        "competencias": 1,
        "version_vocabulario": 1,
        "decision_manual": 1,
    }
    filas = []
    for t in bd.trazas.find(filtro, proyeccion).sort("fecha", -1).limit(limite):
        filas.append(
            {
                "portal": t["portal"],
                "id_aviso": t["id_aviso"],
                "título": t.get("titulo", ""),
                "destino": t.get("destino", ""),
                "motivo": ETIQUETA_MOTIVO.get(t.get("motivo"), t.get("motivo") or ""),
                "competencias": len(t.get("competencias", [])),
                "manual": bool(t.get("decision_manual")),
                "vocabulario": t.get("version_vocabulario"),
                "procesado (Lima)": hora_lima(t.get("fecha")),
            }
        )
    return filas


def detalle(bd: Database, portal: str, id_aviso: str) -> dict[str, Any]:
    clave = {"portal": portal, "id_aviso": id_aviso}
    return {
        "crudo": bd.avisos_crudos.find_one(clave, {"_id": 0}),
        "traza": bd.trazas.find_one(clave, {"_id": 0}),
        "oferta": bd.ofertas_laborales.find_one(
            {"fuente.portal": portal, "fuente.id_aviso": id_aviso}, {"_id": 0}
        ),
        "descarte": bd.ofertas_descartadas.find_one(clave, {"_id": 0}),
        "candidatos": list(bd.candidatos_competencia.find(clave, {"_id": 0})),
    }


def unidades_resaltadas(traza: dict[str, Any]) -> list[tuple[str | None, str]]:
    """(sección, HTML) por unidad, con las coincidencias marcadas: literal o semántica."""
    por_unidad: dict[int, list[dict]] = {}
    for c in traza.get("coincidencias", []):
        por_unidad.setdefault(c["unidad"], []).append(c)
    salida = []
    for i, unidad in enumerate(traza.get("unidades", [])):
        salida.append((unidad.get("seccion"), resaltar(unidad["texto"], por_unidad.get(i, []))))
    return salida


def resaltar(texto: str, coincidencias: list[dict]) -> str:
    # Mismo tramo con dos términos (variante colisionada): se muestra una marca con ambos.
    tramos: dict[tuple[int, int], list[dict]] = {}
    for c in coincidencias:
        tramos.setdefault((c["inicio"], c["fin"]), []).append(c)
    partes, cursor = [], 0
    for (inicio, fin), grupo in sorted(tramos.items()):
        if inicio < cursor:  # solapado con el anterior: no se marca dos veces
            continue
        partes.append(html.escape(texto[cursor:inicio]))
        semantica = grupo[0]["via"] == "semantica"
        titulo = ", ".join(
            c["termino"] + (f" ({c['puntaje']:.3f})" if c.get("puntaje") is not None else "")
            for c in grupo
        )
        clase = "sem" if semantica else "lit"
        partes.append(
            f'<mark class="{clase}" title="{html.escape(titulo)}">'
            f"{html.escape(texto[inicio:fin])}</mark>"
            f'<sup class="{clase}">{html.escape(titulo)}</sup>'
        )
        cursor = fin
    partes.append(html.escape(texto[cursor:]))
    return "".join(partes)


def conteos(bd: Database) -> dict[str, int]:
    return {
        "crudos": bd.avisos_crudos.count_documents({}),
        "publicados": bd.ofertas_laborales.count_documents({}),
        "descartados": bd.ofertas_descartadas.count_documents({}),
        "candidatos pendientes": bd.candidatos_competencia.count_documents({"estado": "pendiente"}),
    }


def _escapar_regex(texto: str) -> str:
    import re

    return re.escape(texto)


def fijar_via_semantica(ruta: Path, activa: bool) -> None:
    """Cambia solo la línea `usar_via_semantica` del TOML; los comentarios se conservan."""
    import re

    texto = ruta.read_text(encoding="utf-8")
    nuevo, n = re.subn(
        r"^usar_via_semantica\s*=\s*(true|false)",
        f"usar_via_semantica = {'true' if activa else 'false'}",
        texto,
        flags=re.MULTILINE,
    )
    if n != 1:
        raise ValueError("no se encontró `usar_via_semantica` en los parámetros")
    ruta.write_text(nuevo, encoding="utf-8", newline="\n")
