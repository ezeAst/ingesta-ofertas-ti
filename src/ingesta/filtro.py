"""Filtro de pertinencia (riesgo R3 de R 2.1).

La categoría del portal ya acota la búsqueda; esta es la segunda barrera: el aviso debe tener
al menos N competencias técnicas halladas por coincidencia literal. Se usa solo la vía literal
porque es determinista; la semántica depende de un umbral todavía sin calibrar.
"""


def es_de_ti(tecnicas_literales: set[str], minimo: int) -> bool:
    return len(tecnicas_literales) >= minimo
