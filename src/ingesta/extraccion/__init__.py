"""Extractor de competencias (Anexo J §5 y §6): vía literal, vía semántica y nivel requerido."""

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
    """Tramo dudoso que va a la cola de revisión humana (criterio CI1 de R 1.3)."""

    indice: int
    unidad: str
    tramo: str
    termino_cercano: str
    puntaje: float
