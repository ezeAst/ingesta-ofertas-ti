"""Clientes de fuente (Anexo J §5): uno por portal, con la misma interfaz.

Cada fuente recorre su canal estructurado y entrega, por cada aviso nuevo, un `AvisoObtenido`
con el contenido original, o un `FalloAviso` con el motivo. El aislamiento por fuente es la
mitigación del riesgo R1: si un portal cambia, el otro no se entera.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class AvisoObtenido:
    portal: str
    id_aviso: str
    url: str
    contenido: dict[str, Any]


@dataclass(frozen=True)
class FalloAviso:
    portal: str
    referencia: str
    motivo: str


class Fuente(Protocol):
    portal: str
    vistos: int

    def listar(self, conocidos: set[str]) -> Iterator[AvisoObtenido | FalloAviso]: ...
