"""Eliminación de datos de contacto antes de guardar el crudo (compromiso 6, Ley N.° 29733).

No se puede distinguir con seguridad un correo o teléfono de una persona natural de uno
corporativo, así que se eliminan todos: es la opción que minimiza datos personales.
"""

import re
from typing import Any

MARCA = "[contacto eliminado]"

_PATRONES = [
    re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),  # correo
    re.compile(r"(?<!\d)(?:\+?51[\s.-]?)?9\d{2}[\s.-]?\d{3}[\s.-]?\d{3}(?!\d)"),  # celular
    re.compile(r"\(0?1\)\s?\d{3}[\s.-]?\d{4}(?!\d)"),  # fijo de Lima con prefijo
]


def eliminar_contactos(texto: str) -> tuple[str, int]:
    total = 0
    for patron in _PATRONES:
        texto, n = patron.subn(MARCA, texto)
        total += n
    return texto, total


def limpiar_estructura(valor: Any) -> tuple[Any, int]:
    """Aplica `eliminar_contactos` a todas las cadenas de un JSON, sin mutar el original."""
    if isinstance(valor, str):
        return eliminar_contactos(valor)
    if isinstance(valor, dict):
        total, limpio = 0, {}
        for clave, v in valor.items():
            limpio[clave], n = limpiar_estructura(v)
            total += n
        return limpio, total
    if isinstance(valor, list):
        total, limpia = 0, []
        for v in valor:
            nuevo, n = limpiar_estructura(v)
            limpia.append(nuevo)
            total += n
        return limpia, total
    return valor, 0
