"""Recorrido de un aviso desde el crudo hasta su destino (Anexo J §6; orden: decisión I20).

extracción → ¿alguna competencia? (sin_competencias) → ¿es de TI? (no_TI)
→ ¿ya existe? (duplicado)
→ validación y escritura (esquema | publicado)

La extracción va primero porque el filtro TI necesita las coincidencias literales; con el orden
del diagrama J3 el motivo «sin_competencias» nunca se alcanzaría.
"""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from ingesta.almacen import ColaCandidatos, Destinos, EsquemaInvalido, Trazas
from ingesta.avisos import AvisoNormalizado, armar_oferta, normalizar_aviso
from ingesta.deduplicacion import Deduplicador
from ingesta.extraccion import Candidato
from ingesta.extraccion.extractor import Extractor, ResultadoExtraccion
from ingesta.filtro import es_de_ti


@dataclass(frozen=True)
class Resultado:
    destino: str  # «publicado» o «descartado»
    motivo: str | None = None
    competencias: int = 0
    candidatos_nuevos: int = 0


class Procesador:
    def __init__(
        self,
        extractor: Extractor,
        version_vocabulario: int,
        minimo_tecnicas: int,
        dedup: Deduplicador,
        destinos: Destinos,
        cola: ColaCandidatos,
        ahora: Callable[[], datetime],
        trazas: Trazas | None = None,
        via_semantica: bool = True,
    ):
        self._extractor = extractor
        self._version = version_vocabulario
        self._minimo = minimo_tecnicas
        self._dedup = dedup
        self._destinos = destinos
        self._cola = cola
        self._ahora = ahora
        self._trazas = trazas
        self._via_semantica = via_semantica

    def procesar(self, crudo: dict[str, Any]) -> Resultado:
        aviso = normalizar_aviso(crudo)
        r = self._extractor.extraer(aviso.unidades)
        manual = (
            self._trazas.decision_manual(aviso.portal, aviso.id_aviso) if self._trazas else None
        )
        if manual and manual.get("accion") == "publicar":
            return self._publicar(aviso, r, manual["competencias"], manual=True)

        if not r.competencias:
            nuevos = self._encolar(aviso, r.candidatos)
            detalle = {"tramos_encolados": [c.tramo for c in r.candidatos]}
            return self._descartar(aviso, r, "sin_competencias", detalle, nuevos)

        tecnicas = r.tecnicas_literales()
        if not es_de_ti(tecnicas, self._minimo):
            return self._descartar(aviso, r, "no_TI", {"tecnicas_literales": sorted(tecnicas)})

        original = self._dedup.buscar_original(self._firma(aviso))
        if original is not None:
            detalle = {"original": {"portal": original.portal, "id_aviso": original.id_aviso}}
            return self._descartar(aviso, r, "duplicado", detalle)

        return self._publicar(aviso, r, r.competencias, manual=False)

    def _firma(self, aviso: AvisoNormalizado):
        return self._dedup.firma(
            aviso.portal,
            aviso.id_aviso,
            aviso.empresa,
            aviso.titulo,
            aviso.descripcion,
            aviso.fecha_publicacion or aviso.fecha_extraccion,
        )

    def _publicar(
        self,
        aviso: AvisoNormalizado,
        r: ResultadoExtraccion,
        competencias: list[dict[str, Any]],
        *,
        manual: bool,
    ) -> Resultado:
        try:
            self._destinos.publicar(armar_oferta(aviso, competencias))
        except EsquemaInvalido as error:
            return self._descartar(aviso, r, "esquema", {"error": str(error)[:2000]})
        self._dedup.registrar(self._firma(aviso))
        nuevos = self._encolar(aviso, r.candidatos)
        detalle = {"decision_manual": True} if manual else {}
        self._trazar(aviso, r, "publicado", None, detalle, competencias)
        return Resultado("publicado", None, len(competencias), nuevos)

    def _descartar(
        self,
        aviso: AvisoNormalizado,
        r: ResultadoExtraccion,
        motivo: str,
        detalle: dict[str, Any],
        nuevos: int = 0,
    ) -> Resultado:
        self._destinos.descartar(aviso.portal, aviso.id_aviso, motivo, detalle, self._ahora())
        self._trazar(aviso, r, "descartado", motivo, detalle, r.competencias)
        return Resultado("descartado", motivo, 0, nuevos)

    def _trazar(self, aviso, r, destino, motivo, detalle, competencias) -> None:
        if self._trazas is None:
            return
        self._trazas.guardar(
            aviso.portal,
            aviso.id_aviso,
            {
                "fecha": self._ahora(),
                "version_vocabulario": self._version,
                "via_semantica": self._via_semantica,
                "destino": destino,
                "motivo": motivo,
                "detalle": detalle,
                "titulo": aviso.titulo,
                "descripcion": aviso.descripcion,
                "unidades": [{"texto": u.texto, "seccion": u.seccion} for u in aviso.unidades],
                "coincidencias": [asdict(c) for c in r.literales + r.semanticas],
                "candidatos": [asdict(c) for c in r.candidatos],
                "competencias": competencias,
            },
        )

    def _encolar(self, aviso: AvisoNormalizado, candidatos: list[Candidato]) -> int:
        """Solo se encolan tramos de avisos publicados o sin competencias: los de avisos ajenos a
        TI o duplicados no aportan al vocabulario."""
        return sum(
            self._cola.encolar(aviso.portal, aviso.id_aviso, c, self._version, self._ahora())
            for c in candidatos
        )
