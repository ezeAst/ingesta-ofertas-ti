"""Iniciador de campaña (Anexo J §5): campaña nueva o reproceso del crudo."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pymongo import DESCENDING
from pymongo.database import Database
from spacy.language import Language

from ingesta.almacen import ColaCandidatos, Destinos, RepositorioCrudo, Trazas
from ingesta.avisos import normalizar_aviso
from ingesta.cliente_http import ClienteHTTP, FuenteDetenida
from ingesta.config import DIR_LOGS, Parametros
from ingesta.deduplicacion import Deduplicador
from ingesta.extraccion.extractor import Extractor
from ingesta.extraccion.lexica import ComparadorLexico
from ingesta.extraccion.literal import ComparadorLiteral
from ingesta.extraccion.semantica import ComparadorSemantico, Embebedor
from ingesta.fuentes import FalloAviso, Fuente
from ingesta.fuentes.bumeran import FuenteBumeran
from ingesta.fuentes.computrabajo import FuenteComputrabajo
from ingesta.procesamiento import Procesador
from ingesta.registro import (
    Acumulador,
    abrir_ejecucion,
    bitacora,
    cerrar_ejecucion,
    estado_corrida,
    tasa_exito,
)
from ingesta.robots import ResultadoRobots, verificar_robots
from ingesta.vocabulario import Vocabulario

_DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
PORTALES = ("Bumeran", "Computrabajo")
CUALQUIER_DIA = "cualquiera"
log = logging.getLogger("ingesta.campana")


class CampanaFueraDeDia(Exception):
    """Compromiso 4: las campañas nuevas solo se inician el día configurado."""


@dataclass
class Dependencias:
    bd: Database
    params: Parametros
    vocab: Vocabulario
    nlp: Language
    embebedor: Embebedor
    reloj: Callable[[], float] = time.monotonic
    dormir: Callable[[float], None] = time.sleep
    ahora: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    dir_logs: Path = DIR_LOGS
    modelo: str = ""
    qdrant: Any = None  # QdrantClient; sin él no se actualiza la base de conocimiento (R 2.4)


def ejecutar_campana(
    dep: Dependencias, portales: list[str] | None = None, limite: int | None = None
) -> dict[str, Any]:
    """Campaña nueva sobre los portales elegidos (por defecto, ambos).

    `limite` corta cada portal tras N avisos nuevos: sirve para corridas de prueba.
    """
    p = dep.params
    portales = list(portales or PORTALES)
    desconocidos = set(portales) - set(PORTALES)
    if desconocidos:
        raise ValueError(f"portales desconocidos: {sorted(desconocidos)}")
    inicio = dep.ahora()
    dia = _DIAS[inicio.astimezone(ZoneInfo(p.campana.zona_horaria)).weekday()]
    if p.campana.dia_permitido != CUALQUIER_DIA and dia != p.campana.dia_permitido:
        raise CampanaFueraDeDia(
            f"hoy es {dia}; las campañas nuevas se inician el {p.campana.dia_permitido}"
        )

    with bitacora(dep.dir_logs, "campana", inicio) as ruta_log:
        ejecucion = abrir_ejecucion(
            dep, "campana", inicio, ruta_log, portales=portales, limite=limite
        )
        clientes = {
            nombre: ClienteHTTP(p.http, reloj=dep.reloj, dormir=dep.dormir) for nombre in portales
        }
        try:
            robots = _verificar_robots(dep, clientes)
            permitido = all(r.permitido for r in robots)
            acumulado, fuentes = Acumulador(), {}
            if permitido:
                procesador = _procesador(dep, _dedup_desde_bd(dep))
                crudo = RepositorioCrudo(dep.bd)
                constructores = {
                    "Bumeran": lambda: FuenteBumeran(clientes["Bumeran"], p.fuentes.bumeran),
                    "Computrabajo": lambda: FuenteComputrabajo(
                        clientes["Computrabajo"], p.fuentes.computrabajo
                    ),
                }
                for nombre in portales:
                    fuente = constructores[nombre]()
                    fuentes[nombre] = _recorrer(
                        dep, fuente, clientes[nombre], crudo, procesador, acumulado, limite
                    )
            else:
                log.warning("robots.txt: campaña detenida antes de consultar los portales")
        finally:
            for cliente in clientes.values():
                cliente.cerrar()

        tasas = {nombre: f["tasa_exito"] for nombre, f in fuentes.items()}
        estado, motivos = estado_corrida(tasas, permitido, p.corrida.tasa_exito_minima)
        motivos += [
            f"{nombre}: detenida por {f['corte']}" for nombre, f in fuentes.items() if f["corte"]
        ]
        estado = "fallida" if motivos else estado
        ejecucion = cerrar_ejecucion(
            dep,
            ejecucion,
            estado,
            motivos,
            acumulado.como_documento(),
            robots=[_robots_doc(r) for r in robots],
            fuentes=fuentes,
        )
    return _actualizar_base(dep, ejecucion)


def ejecutar_reproceso(dep: Dependencias) -> dict[str, Any]:
    """Relee el crudo y repite el flujo desde la segmentación con el vocabulario vigente.
    No hace ninguna solicitud de red. La deduplicación se recalcula en orden de llegada."""
    inicio = dep.ahora()
    with bitacora(dep.dir_logs, "reproceso", inicio) as ruta_log:
        ejecucion = abrir_ejecucion(dep, "reproceso", inicio, ruta_log)
        procesador = _procesador(dep, _dedup_vacio(dep))
        acumulado = Acumulador()
        for crudo in RepositorioCrudo(dep.bd).todos():
            acumulado.sumar(procesador.procesar(crudo))
        ejecucion = cerrar_ejecucion(dep, ejecucion, "exitosa", [], acumulado.como_documento())
    return _actualizar_base(dep, ejecucion)


def _actualizar_base(dep: Dependencias, ejecucion: dict[str, Any]) -> dict[str, Any]:
    """V11: tras cada campaña o reproceso se sincroniza Qdrant. Si falla, la corrida conserva su
    estado y queda anotado que la base de conocimiento está desactualizada."""
    if dep.qdrant is None:
        base: dict[str, Any] = {"estado": "omitida"}
    else:
        from ingesta.conocimiento.vectorizacion import ejecutar_vectorizacion

        try:
            base = {"estado": "actualizada", "ejecucion": ejecutar_vectorizacion(dep)["_id"]}
        except Exception as error:
            log.warning("base de conocimiento desactualizada: %s", error)
            base = {"estado": "desactualizada", "error": str(error)}
    dep.bd.ejecuciones.update_one({"_id": ejecucion["_id"]}, {"$set": {"base_conocimiento": base}})
    return {**ejecucion, "base_conocimiento": base}


def _recorrer(
    dep,
    fuente: Fuente,
    cliente: ClienteHTTP,
    crudo: RepositorioCrudo,
    procesador,
    acumulado,
    limite: int | None = None,
) -> dict:
    metricas: dict[str, Any] = {"nuevos": 0, "fallidos": 0, "motivos_fallo": {}, "corte": None}
    try:
        for item in fuente.listar(crudo.conocidos(fuente.portal)):
            if isinstance(item, FalloAviso):
                metricas["fallidos"] += 1
                metricas["motivos_fallo"][item.motivo] = (
                    metricas["motivos_fallo"].get(item.motivo, 0) + 1
                )
                log.warning(
                    "%s: aviso fallido (%s) %s", fuente.portal, item.motivo, item.referencia
                )
                continue
            documento = crudo.guardar(item, dep.ahora())
            metricas["nuevos"] += 1
            acumulado.contactos += documento.get("contactos_eliminados", 0)
            resultado = procesador.procesar(documento)
            acumulado.sumar(resultado)
            log.info(
                "%s %s -> %s %s",
                fuente.portal,
                item.id_aviso,
                resultado.destino,
                resultado.motivo or "",
            )
            if limite is not None and metricas["nuevos"] >= limite:
                log.info("%s: límite de %s avisos nuevos alcanzado", fuente.portal, limite)
                break
    except FuenteDetenida as corte:
        metricas["corte"] = str(corte)
    metricas.update(
        vistos=fuente.vistos,
        solicitudes=cliente.contadores.solicitudes,
        rechazos=cliente.contadores.rechazos,
        tasa_exito=tasa_exito(metricas["nuevos"], metricas["fallidos"]),
    )
    if hasattr(fuente, "urls_por_patron"):
        metricas["urls_por_patron"] = fuente.urls_por_patron
    return metricas


def _verificar_robots(dep: Dependencias, clientes: dict[str, ClienteHTTP]) -> list[ResultadoRobots]:
    anterior = dep.bd.ejecuciones.find_one(
        {"modo": "campana", "robots": {"$exists": True}}, sort=[("inicio", DESCENDING)]
    )
    huellas = {r["url"]: r["huella"] for r in (anterior or {}).get("robots", [])}
    fuentes = dep.params.fuentes
    resultados = []
    por_portal = {"Bumeran": fuentes.bumeran, "Computrabajo": fuentes.computrabajo}
    for nombre, pf in ((n, por_portal[n]) for n in clientes):
        r = verificar_robots(
            clientes[nombre],
            pf.robots,
            pf.rutas_vigiladas,
            dep.params.http.user_agent,
            huellas.get(pf.robots),
        )
        log.info(
            "robots %s: permitido=%s cambio=%s prohibidas=%s",
            pf.robots,
            r.permitido,
            r.cambio,
            r.prohibidas,
        )
        resultados.append(r)
    return resultados


def _procesador(dep: Dependencias, dedup: Deduplicador) -> Procesador:
    ex = dep.params.extraccion
    literal = ComparadorLiteral(dep.vocab, dep.nlp, ex.terminos_con_contexto)
    semantico = None
    if ex.usar_via_semantica:
        semantico = ComparadorSemantico(
            dep.vocab,
            dep.embebedor,
            ex.prefijo_e5,
            ex.umbral_similitud,
            ex.umbral_candidato,
            ex.min_palabras_tramo,
        )
        semantico.preparar()
    lexico = ComparadorLexico(dep.vocab, ex.via_lexica) if ex.via_lexica.usar else None
    extractor = Extractor(
        dep.nlp, literal, semantico, dep.vocab, dep.params.nivel_requerido, lexico
    )
    return Procesador(
        extractor,
        dep.vocab.version,
        dep.params.filtro_ti.minimo_competencias_tecnicas,
        dedup,
        Destinos(dep.bd),
        ColaCandidatos(dep.bd),
        dep.ahora,
        Trazas(dep.bd),
        via_semantica=ex.usar_via_semantica,
    )


def _dedup_vacio(dep: Dependencias) -> Deduplicador:
    d = dep.params.deduplicacion
    return Deduplicador(d.ventana_dias, d.tamano_shingle, d.umbral_jaccard)


def _dedup_desde_bd(dep: Dependencias) -> Deduplicador:
    """En una campaña, los avisos nuevos se comparan también con los ya publicados."""
    dedup = _dedup_vacio(dep)
    for oferta in dep.bd.ofertas_laborales.find():
        f = oferta["fuente"]
        dedup.registrar(
            dedup.firma(
                f["portal"],
                f["id_aviso"],
                oferta["empresa"]["nombre"],
                oferta["titulo"],
                oferta["descripcion"],
                oferta.get("fecha_publicacion") or f["fecha_extraccion"],
            )
        )
    return dedup


def _robots_doc(r: ResultadoRobots) -> dict[str, Any]:
    return {
        "url": r.url,
        "permitido": r.permitido,
        "prohibidas": r.prohibidas,
        "huella": r.huella,
        "cambio": r.cambio,
        "texto": r.texto,
    }


__all__ = [
    "CampanaFueraDeDia",
    "Dependencias",
    "ejecutar_campana",
    "ejecutar_reproceso",
    "normalizar_aviso",
]
