"""Extractor de competencias (Anexo J §5 y §6): vía literal, vía semántica, vía léxica (solo
candidatos) y nivel requerido."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Coincidencia:
    """Mención de una competencia del vocabulario dentro de una unidad de requisito."""

    termino: str
    categoria: str
    unidad: int  # índice de la unidad dentro del aviso
    inicio: int  # posición del tramo dentro del texto de la unidad
    fin: int
    texto: str
    via: str = "literal"  # «literal» o «semantica»
    puntaje: float | None = None


@dataclass(frozen=True)
class Candidato:
    """Tramo dudoso que va a la cola de revisión humana (criterio CI1 de R 1.3).

    `origen`: «embedding» (vía semántica, con término cercano y puntaje) o «lexico» (vía por
    descarte, sin ninguno de los dos)."""

    indice: int
    unidad: str
    tramo: str
    termino_cercano: str | None
    puntaje: float | None
    origen: str = "embedding"
