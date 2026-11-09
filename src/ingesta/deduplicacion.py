"""Deduplicador (riesgo R4 de R 2.1): clave de bloqueo y similitud de texto (Burk et al., 2017).

Clave: empresa normalizada. Dentro de la clave y de la ventana de días, un aviso es duplicado si
la similitud de Jaccard entre los *shingles* de su descripción supera su umbral y la de las
palabras del título supera el suyo. El título no va en la clave porque las empresas publican el
mismo aviso cambiando la ciudad o un sufijo («… para la ciudad de CUSCO»), y la ventana cubre
las republicaciones (calibración de R 2.4, 2026-10-27).
Sobrevive el primero visto; el resto va a descartes con motivo «duplicado».
"""

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

_FORMAS_SOCIETARIAS = {"sac", "saa", "sa", "srl", "eirl", "sacs", "ltda"}


def normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", sin_tildes.lower()).strip()


def normalizar_empresa(nombre: str) -> str:
    # «S.A.C.» → «s a c» → «sac»: se juntan las letras sueltas antes de quitar la forma societaria.
    tokens = re.sub(r"\b(\w) (?=\w\b)", r"\1", normalizar(nombre)).split()
    while tokens and tokens[-1] in _FORMAS_SOCIETARIAS:
        tokens.pop()
    return " ".join(tokens)


def shingles(texto: str, k: int) -> frozenset[tuple[str, ...]]:
    tokens = normalizar(texto).split()
    if len(tokens) < k:
        return frozenset({tuple(tokens)})
    return frozenset(tuple(tokens[i : i + k]) for i in range(len(tokens) - k + 1))


def jaccard(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a or b else 0.0


@dataclass(frozen=True)
class Firma:
    portal: str
    id_aviso: str
    clave: str
    fecha: datetime
    tejas: frozenset = field(repr=False)
    palabras_titulo: frozenset = field(default=frozenset(), repr=False)


class Deduplicador:
    def __init__(
        self,
        ventana_dias: int,
        tamano_shingle: int,
        umbral_jaccard: float,
        umbral_titulo: float,
    ):
        self._ventana = ventana_dias
        self._k = tamano_shingle
        self._umbral = umbral_jaccard
        self._umbral_titulo = umbral_titulo
        self._indice: dict[str, list[Firma]] = defaultdict(list)

    def firma(
        self,
        portal: str,
        id_aviso: str,
        empresa: str,
        titulo: str,
        descripcion: str,
        fecha: datetime,
    ) -> Firma:
        return Firma(
            portal,
            id_aviso,
            normalizar_empresa(empresa),
            fecha,
            shingles(descripcion, self._k),
            frozenset(normalizar(titulo).split()),
        )

    def buscar_original(self, firma: Firma) -> Firma | None:
        for otra in self._indice[firma.clave]:
            if (otra.portal, otra.id_aviso) == (firma.portal, firma.id_aviso):
                continue
            if abs((firma.fecha - otra.fecha).days) > self._ventana:
                continue
            if jaccard(firma.palabras_titulo, otra.palabras_titulo) < self._umbral_titulo:
                continue
            if jaccard(firma.tejas, otra.tejas) >= self._umbral:
                return otra
        return None

    def registrar(self, firma: Firma) -> None:
        self._indice[firma.clave].append(firma)
