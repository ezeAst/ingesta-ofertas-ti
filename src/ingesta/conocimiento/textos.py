"""Textos que se vectorizan por oferta («R 2.4 - Decisiones de diseno.md», V2, V3 y V10).

Una oferta es un punto con tres vectores: `titulo`, `competencias` (título + nombres canónicos)
y `fragmentos` (la descripción por partes, sin «Beneficios y empresa»).
"""

import hashlib
import uuid
from collections.abc import Callable
from typing import Any

from ingesta.normalizacion import SECCION_EXCLUIDA, segmentar

VECTORES = ("titulo", "competencias", "fragmentos")
# Espacio de nombres fijo: el mismo aviso da siempre el mismo id de punto.
NAMESPACE = uuid.UUID("7f1c2a64-2b0e-4a55-9c0f-5a3c0e6b2d41")
SEPARADOR = " — "
_ESPECIALES = 2  # el tokenizador añade un token de inicio y uno de fin a cada texto

ContarTokens = Callable[[list[str]], list[int]]


def id_punto(portal: str, id_aviso: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{portal}:{id_aviso}"))


def huella(oferta: dict[str, Any], configuracion: str = "") -> str:
    """Cambia si cambia lo que se vectoriza (título, descripción o competencias) o cómo se
    vectoriza (`configuracion`: modelo, prefijo y tamaño de fragmento)."""
    partes = [configuracion, oferta["titulo"], oferta["descripcion"], *_nombres(oferta)]
    return hashlib.sha256("\n".join(partes).encode()).hexdigest()


def texto_titulo(oferta: dict[str, Any], prefijo: str) -> str:
    return f"{prefijo}{oferta['titulo']}"


def texto_competencias(oferta: dict[str, Any], prefijo: str) -> str:
    unicos = list(dict.fromkeys(_nombres(oferta)))
    return f"{prefijo}{oferta['titulo']}. Competencias: {', '.join(unicos)}"


def fragmentar(
    oferta: dict[str, Any], prefijo: str, max_tokens: int, contar_tokens: ContarTokens
) -> list[str]:
    """Agrupa las unidades de la descripción en fragmentos de hasta `max_tokens`.

    Un fragmento se cierra al cambiar de sección o al llenarse. Si se llenó dentro de la misma
    sección, el siguiente repite su última unidad (solapamiento). Una unidad que sola pasa el
    límite queda en su propio fragmento y el servicio la recorta. Sin unidades útiles, el título
    hace de único fragmento: el vector multivector necesita al menos uno.
    """
    cabecera = f"{prefijo}{oferta['titulo']}"
    unidades = [
        u
        for u in segmentar(oferta["descripcion"], oferta["fuente"]["portal"])
        if u.seccion != SECCION_EXCLUIDA
    ]
    if not unidades:
        return [cabecera]
    # Una sola llamada por oferta: los tokens del fragmento se estiman sumando los de sus
    # unidades sin los especiales. El margen hasta 512 absorbe la diferencia.
    base, *netos = contar_tokens([cabecera + SEPARADOR.rstrip()] + [u.texto for u in unidades])
    netos = [n - _ESPECIALES for n in netos]

    grupos: list[list[str]] = []
    actual: list[int] = []
    tamano = base
    for i, unidad in enumerate(unidades):
        if actual:
            misma_seccion = unidad.seccion == unidades[actual[-1]].seccion
            if not misma_seccion or tamano + netos[i] > max_tokens:
                grupos.append([unidades[j].texto for j in actual])
                solapa = misma_seccion and len(actual) > 1
                previa = actual[-1]
                actual, tamano = [], base
                if solapa and base + netos[previa] + netos[i] <= max_tokens:
                    actual, tamano = [previa], base + netos[previa]
        actual.append(i)
        tamano += netos[i]
    grupos.append([unidades[j].texto for j in actual])
    return [f"{cabecera}{SEPARADOR}{' '.join(g)}" for g in grupos]


def _nombres(oferta: dict[str, Any]) -> list[str]:
    return [c["nombre"] for c in oferta.get("competencias", [])]
