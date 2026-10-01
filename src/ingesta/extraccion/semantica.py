"""Vía semántica (Anexo J §6): solo para unidades sin coincidencia literal.

Se vectorizan los grupos nominales de la unidad y la unidad completa, se comparan solo con las
variantes descriptivas y se retiene el mayor puntaje. Los términos canónicos y las variantes
literales ya los cubre la vía literal; un término sin descriptivas no participa aquí. Los grupos
nominales con menos de `min_palabras_tramo` palabras no se comparan. Sobre el
umbral se acepta la competencia; entre el umbral de candidato y el umbral, el tramo se encola
para revisión humana; por debajo, se ignora.
"""

from typing import Protocol

import numpy as np
from spacy.tokens import Doc

from ingesta.extraccion import Candidato, Coincidencia
from ingesta.vocabulario import Vocabulario


class Embebedor(Protocol):
    def vectorizar(self, textos: list[str]) -> np.ndarray: ...


class ComparadorSemantico:
    def __init__(
        self,
        vocab: Vocabulario,
        embebedor: Embebedor,
        prefijo: str,
        umbral: float,
        umbral_candidato: float,
        min_palabras_tramo: int = 1,
    ):
        self._vocab = vocab
        self._embebedor = embebedor
        self._prefijo = prefijo
        self.umbral = umbral
        self.umbral_candidato = umbral_candidato
        self.min_palabras_tramo = min_palabras_tramo
        self._objetivos: list[tuple[str, str]] = []  # (variante descriptiva, término canónico)
        self._matriz: np.ndarray | None = None

    def preparar(self) -> None:
        """Vectoriza una vez por ejecución las variantes descriptivas del vocabulario."""
        self._objetivos = [
            (texto, t["nombre"]) for t in self._vocab.terminos for texto in t["descriptivas"]
        ]
        self._matriz = (
            self._embebedor.vectorizar([self._prefijo + texto for texto, _ in self._objetivos])
            if self._objetivos
            else np.zeros((0, 0))
        )

    def evaluar(
        self, docs: list[Doc], indices: list[int]
    ) -> tuple[list[Coincidencia], list[Candidato]]:
        if self._matriz is None:
            raise RuntimeError("llamar a preparar() antes de evaluar()")
        if not self._objetivos:
            return [], []
        tramos = [
            (i, texto, ini, fin)
            for i in indices
            for texto, ini, fin in _tramos(docs[i], self.min_palabras_tramo)
        ]
        if not tramos:
            return [], []
        vectores = self._embebedor.vectorizar([self._prefijo + texto for _, texto, _, _ in tramos])
        similitudes = vectores @ self._matriz.T
        mejor_objetivo = similitudes.argmax(axis=1)
        mejor_puntaje = similitudes.max(axis=1)

        aceptadas: list[Coincidencia] = []
        candidatos: list[Candidato] = []
        for i in indices:
            filas = [k for k, t in enumerate(tramos) if t[0] == i]
            if not filas:
                continue
            k = max(filas, key=lambda f: mejor_puntaje[f])
            puntaje = float(mejor_puntaje[k])
            termino = self._objetivos[mejor_objetivo[k]][1]
            _, texto, ini, fin = tramos[k]
            if puntaje >= self.umbral:
                aceptadas.append(
                    Coincidencia(
                        termino=termino,
                        categoria=self._vocab.termino(termino)["categoria"],
                        unidad=i,
                        inicio=ini,
                        fin=fin,
                        texto=texto,
                        via="semantica",
                        puntaje=round(puntaje, 4),
                    )
                )
            elif puntaje >= self.umbral_candidato:
                candidatos.append(Candidato(i, docs[i].text, texto, termino, round(puntaje, 4)))
        return aceptadas, candidatos


def _tramos(doc: Doc, min_palabras: int) -> list[tuple[str, int, int]]:
    """Grupos nominales de al menos `min_palabras` palabras y la unidad completa. Los grupos
    cortos («Horario», «, Informática») se parecen a casi cualquier variante en E5."""
    tramos: dict[str, tuple[str, int, int]] = {}
    try:
        for grupo in doc.noun_chunks:
            if len(grupo.text) >= 2 and len(grupo.text.split()) >= min_palabras:
                tramos.setdefault(grupo.text, (grupo.text, grupo.start_char, grupo.end_char))
    except ValueError:  # doc sin análisis sintáctico: solo la unidad completa
        pass
    tramos.setdefault(doc.text, (doc.text, 0, len(doc.text)))
    return list(tramos.values())
