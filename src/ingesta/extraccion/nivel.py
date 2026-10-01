"""Nivel requerido por regla léxica (decisión I5).

Se busca un marcador de nivel en la misma unidad que la competencia y a no más de
`distancia_maxima` caracteres; si hay varios, se usa el más cercano. Sin marcador, el campo se
omite (R 1.4 lo permite). Los años de experiencia no se traducen a nivel: cualquier equivalencia
sería arbitraria.
"""

import re

from ingesta.config import ParamsNivel

_VALOR = {"basico": "básico", "intermedio": "intermedio", "avanzado": "avanzado"}


def asignar_nivel(texto: str, inicio: int, fin: int, marcadores: ParamsNivel) -> str | None:
    def distancia(h: tuple[int, int, str]) -> int:
        return max(0, h[0] - fin, inicio - h[1])

    hallados: list[tuple[int, int, str]] = []
    for clave in _VALOR:
        for marcador in getattr(marcadores, clave):
            patron = rf"(?<!\w){re.escape(marcador)}(?!\w)"
            hallados += [
                (m.start(), m.end(), clave) for m in re.finditer(patron, texto, re.IGNORECASE)
            ]
    cercanos = [h for h in hallados if distancia(h) <= marcadores.distancia_maxima]
    if not cercanos:
        return None
    return _VALOR[min(cercanos, key=distancia)[2]]
