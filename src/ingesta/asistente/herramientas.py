"""Herramientas que el LLM puede llamar (tool calling, decisión V9 de R 2.4) y su validación.

El LLM solo propone argumentos: el código los valida contra el catálogo (los valores fuera del
vocabulario de R 1.3 se descartan) y ejecuta la búsqueda.
"""

from dataclasses import dataclass

from pymongo.database import Database

_LISTA = {"type": "array", "items": {"type": "string"}}

HERRAMIENTAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "buscar_ofertas",
            "description": "Busca ofertas laborales de TI relevantes para la pregunta y cuenta sus competencias.",
            "parameters": {
                "type": "object",
                "properties": {
                    "consulta": {
                        "type": "string",
                        "description": "Búsqueda completa en español, resolviendo referencias del historial.",
                    },
                    "consulta_alternativa": {
                        "type": "string",
                        "description": "Otra forma de buscar lo mismo, con términos técnicos o sinónimos.",
                    },
                    "competencias_exigidas": {
                        **_LISTA,
                        "description": "Competencias que la oferta debe pedir (nombres exactos del catálogo, máximo 3).",
                    },
                    "categorias": {
                        **_LISTA,
                        "description": "Categorías del catálogo, solo si se piden explícitamente.",
                    },
                    "tipos": {**_LISTA, "description": "«técnica» o «transversal»."},
                    "niveles": {
                        **_LISTA,
                        "description": "Nivel de dominio de una competencia exigida.",
                    },
                },
                "required": ["consulta", "consulta_alternativa"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calcular_brecha",
            "description": "Compara las competencias que el usuario dice tener con las que piden las ofertas de un puesto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "puesto": {"type": "string", "description": "Puesto o área de interés."},
                    "competencias_conocidas": {
                        **_LISTA,
                        "description": "Lo que el usuario dice saber (nombres exactos del catálogo).",
                    },
                },
                "required": ["puesto", "competencias_conocidas"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ver_oferta",
            "description": "Muestra el detalle de una oferta de la última respuesta.",
            "parameters": {
                "type": "object",
                "properties": {
                    "numero": {"type": "integer", "description": "Número [n] de la oferta."}
                },
                "required": ["numero"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mostrar_fuentes",
            "description": "Muestra las ofertas en que se basó la última respuesta.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


@dataclass(frozen=True)
class Catalogo:
    """Valores permitidos, tomados de las ofertas publicadas."""

    competencias: tuple[str, ...]
    categorias: tuple[str, ...]
    tipos: tuple[str, ...]
    niveles: tuple[str, ...]

    @classmethod
    def desde_bd(cls, bd: Database) -> "Catalogo":
        ofertas = bd.ofertas_laborales
        return cls(
            competencias=tuple(sorted(ofertas.distinct("competencias.nombre"))),
            categorias=tuple(sorted(ofertas.distinct("competencias.categoria"))),
            tipos=tuple(sorted(ofertas.distinct("competencias.tipo"))),
            niveles=tuple(sorted(ofertas.distinct("competencias.nivel_requerido"))),
        )


def validar(valores, permitidos: tuple[str, ...], maximo: int | None = None) -> tuple[str, ...]:
    """Solo valores del catálogo (sin distinguir mayúsculas), sin repetir y en el orden dado."""
    if not isinstance(valores, list):
        return ()
    por_minuscula = {p.casefold(): p for p in permitidos}
    salida: list[str] = []
    for v in valores:
        canonico = por_minuscula.get(str(v).strip().casefold())
        if canonico and canonico not in salida:
            salida.append(canonico)
    return tuple(salida[:maximo] if maximo else salida)


def texto(valor) -> str:
    return " ".join(str(valor).split()) if isinstance(valor, str | int | float) else ""
