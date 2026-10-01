"""Del documento crudo de cada portal al aviso normalizado y a la oferta del esquema de R 1.4."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ingesta.normalizacion import (
    Unidad,
    html_a_texto,
    quitar_emojis,
    segmentar,
    texto_legible,
)

LIMA = ZoneInfo("America/Lima")
EMPRESA_CONFIDENCIAL = "Confidencial"  # texto que usan los portales (decisión I3)


@dataclass(frozen=True)
class AvisoNormalizado:
    portal: str
    id_aviso: str
    url: str
    fecha_extraccion: datetime
    titulo: str
    descripcion: str
    fecha_publicacion: datetime | None
    empresa: str
    sector: str | None
    unidades: list[Unidad]


def normalizar_aviso(crudo: dict[str, Any]) -> AvisoNormalizado:
    campos = (
        _bumeran(crudo["contenido"])
        if crudo["portal"] == "Bumeran"
        else _computrabajo(crudo["contenido"])
    )
    return AvisoNormalizado(
        portal=crudo["portal"],
        id_aviso=crudo["id_aviso"],
        url=crudo["url"],
        fecha_extraccion=crudo["fecha_extraccion"],
        **campos,
    )


def _bumeran(item: dict[str, Any]) -> dict[str, Any]:
    titulo = _limpiar_titulo(item.get("titulo"))
    detalle = quitar_emojis(item.get("detalle") or "")
    fecha = _fecha(item.get("fechaHoraPublicacion"), "%d-%m-%Y %H:%M:%S") or _fecha(
        item.get("fechaPublicacion"), "%d-%m-%Y"
    )
    return {
        "titulo": titulo,
        "descripcion": texto_legible(detalle, "Bumeran"),
        "fecha_publicacion": fecha,
        "empresa": (item.get("empresa") or "").strip() or EMPRESA_CONFIDENCIAL,
        "sector": None,  # la interfaz de Bumeran no declara sector
        "unidades": _con_titulo(titulo, segmentar(detalle, "Bumeran")),
    }


def _computrabajo(contenido: dict[str, Any]) -> dict[str, Any]:
    jp = contenido["jobposting"]
    titulo = _limpiar_titulo(jp.get("title"))
    descripcion = html_a_texto(quitar_emojis(jp.get("description") or ""))
    organizacion = jp.get("hiringOrganization") or {}
    return {
        "titulo": titulo,
        "descripcion": descripcion,
        "fecha_publicacion": _fecha(jp.get("datePosted"), "%Y-%m-%d"),
        "empresa": (organizacion.get("name") or "").strip() or EMPRESA_CONFIDENCIAL,
        # `industry` del JobPosting: texto libre tal como lo declara el portal (decisión I19).
        "sector": (jp.get("industry") or "").strip() or None,
        "unidades": _con_titulo(titulo, segmentar(descripcion, "Computrabajo")),
    }


def _limpiar_titulo(titulo: str | None) -> str:
    return " ".join(quitar_emojis(titulo or "").split())


def _con_titulo(titulo: str, unidades: list[Unidad]) -> list[Unidad]:
    """El título también es una unidad: «Desarrollador Java» ya declara una competencia."""
    return [Unidad(titulo), *unidades] if titulo else unidades


def _fecha(texto: str | None, formato: str) -> datetime | None:
    try:
        return datetime.strptime(texto, formato).replace(tzinfo=LIMA).astimezone(UTC)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def armar_oferta(aviso: AvisoNormalizado, competencias: list[dict[str, Any]]) -> dict[str, Any]:
    """Documento de `ofertas_laborales`. Lo que el aviso no declara no se escribe: si falta un
    campo obligatorio, el validador de MongoDB lo rechaza y el aviso va a descartes («esquema»)."""
    empresa: dict[str, Any] = {"nombre": aviso.empresa}
    if aviso.sector:
        empresa["sector"] = aviso.sector
    oferta: dict[str, Any] = {
        "titulo": aviso.titulo,
        "descripcion": aviso.descripcion,
        "fuente": {
            "portal": aviso.portal,
            "id_aviso": aviso.id_aviso,
            "url": aviso.url,
            "fecha_extraccion": aviso.fecha_extraccion,
        },
        "empresa": empresa,
        "competencias": competencias,
    }
    if aviso.fecha_publicacion is not None:
        oferta["fecha_publicacion"] = aviso.fecha_publicacion
    return oferta
