"""Colección de Qdrant: un punto por oferta con tres vectores nombrados (V2, V3 y V6)."""

from qdrant_client import QdrantClient, models

from ingesta.conocimiento.textos import VECTORES

_PAGINA = 1000


def asegurar(cliente: QdrantClient, nombre: str, dim: int) -> None:
    """Crea la colección si no existe. `fragmentos` es multivector: la oferta puntúa por su
    fragmento más parecido (comparador MAX_SIM)."""
    if cliente.collection_exists(nombre):
        return
    vectores = {v: models.VectorParams(size=dim, distance=models.Distance.COSINE) for v in VECTORES}
    vectores["fragmentos"].multivector_config = models.MultiVectorConfig(
        comparator=models.MultiVectorComparator.MAX_SIM
    )
    cliente.create_collection(nombre, vectors_config=vectores)


def huellas(cliente: QdrantClient, nombre: str) -> dict[str, str]:
    """Id de punto → huella de la oferta que lo generó."""
    resultado: dict[str, str] = {}
    desde = None
    while True:
        puntos, desde = cliente.scroll(
            nombre, limit=_PAGINA, offset=desde, with_payload=["huella"], with_vectors=False
        )
        resultado.update({str(p.id): p.payload["huella"] for p in puntos})
        if desde is None:
            return resultado
