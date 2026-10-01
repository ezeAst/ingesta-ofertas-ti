"""Orquesta las dos vías y arma la lista `competencias` del esquema de R 1.4."""

from dataclasses import dataclass, field
from typing import Any

from spacy.language import Language

from ingesta.config import ParamsNivel
from ingesta.extraccion import Candidato, Coincidencia
from ingesta.extraccion.literal import ComparadorLiteral
from ingesta.extraccion.nivel import asignar_nivel
from ingesta.extraccion.semantica import ComparadorSemantico
from ingesta.normalizacion import SECCION_EXCLUIDA, Unidad
from ingesta.vocabulario import Vocabulario


@dataclass
class ResultadoExtraccion:
    competencias: list[dict[str, Any]]
    literales: list[Coincidencia]
    semanticas: list[Coincidencia]
    candidatos: list[Candidato]
    _tecnicas_literales: set[str] = field(default_factory=set)

    def tecnicas_literales(self) -> set[str]:
        """Competencias técnicas halladas por coincidencia literal (entrada del filtro TI)."""
        return set(self._tecnicas_literales)


class Extractor:
    def __init__(
        self,
        nlp: Language,
        literal: ComparadorLiteral,
        semantico: ComparadorSemantico | None,
        vocab: Vocabulario,
        niveles: ParamsNivel,
    ):
        self._nlp = nlp
        self._literal = literal
        self._semantico = semantico
        self._vocab = vocab
        self._niveles = niveles

    def extraer(self, unidades: list[Unidad]) -> ResultadoExtraccion:
        docs = list(self._nlp.pipe(u.texto for u in unidades))
        literales = self._literal.buscar(docs)
        con_literal = {c.unidad for c in literales}
        # Beneficios y presentación de la empresa solo pasan por el diccionario.
        sin_literal = [
            i
            for i in range(len(docs))
            if i not in con_literal and unidades[i].seccion != SECCION_EXCLUIDA
        ]
        semanticas, candidatos = (
            self._semantico.evaluar(docs, sin_literal) if self._semantico else ([], [])
        )

        competencias: dict[tuple[str, str], dict[str, Any]] = {}
        for c in sorted(literales + semanticas, key=lambda c: (c.unidad, c.inicio)):
            entrada = competencias.setdefault(
                (c.termino, c.categoria),
                {
                    "nombre": c.termino,
                    "categoria": c.categoria,
                    "tipo": self._vocab.rama(c.categoria),
                },
            )
            if "nivel_requerido" not in entrada:
                nivel = asignar_nivel(docs[c.unidad].text, c.inicio, c.fin, self._niveles)
                if nivel:
                    entrada["nivel_requerido"] = nivel

        tecnicas = {c.termino for c in literales if self._vocab.rama(c.categoria) == "técnica"}
        return ResultadoExtraccion(
            list(competencias.values()), literales, semanticas, candidatos, tecnicas
        )
