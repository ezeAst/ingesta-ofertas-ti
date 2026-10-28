"""Fixtures compartidas. Los datos de prueba son sintéticos: no contienen avisos reales."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ingesta.config import Parametros, cargar_parametros

DIR_FIXTURES = Path(__file__).parent / "fixtures"
XLSX_VOCABULARIO = Path("/resultados/R1.3_Vocabulario_Controlado (1).xlsx")


@pytest.fixture(scope="session")
def params() -> Parametros:
    return cargar_parametros()


@pytest.fixture(scope="session")
def fixtures() -> Path:
    return DIR_FIXTURES


@pytest.fixture(scope="session")
def nlp():
    import spacy

    return spacy.load("es_core_news_md")


@pytest.fixture
def vocab():
    from .utiles import vocab_prueba

    return vocab_prueba()


@pytest.fixture(scope="session")
def params_bow(params) -> Parametros:
    """Umbrales ajustados al embebedor de palabras de las pruebas (no son los de producción).
    Sin mínimo de palabras por tramo: los avisos sintéticos son frases cortas."""
    extraccion = params.extraccion.model_copy(
        update={"umbral_similitud": 0.65, "umbral_candidato": 0.5, "min_palabras_tramo": 1}
    )
    return params.model_copy(update={"extraccion": extraccion})


@pytest.fixture
def bd():
    """Base `ingesta_pruebas` vacía y preparada; nunca se toca la base `ingesta`."""
    import json

    from ingesta.bd import conectar, preparar
    from ingesta.config import RUTA_ESQUEMA, Entorno

    entorno = Entorno()
    base = conectar(entorno, nombre_bd=f"{entorno.mongo_bd}_pruebas")
    for nombre in base.list_collection_names():
        base.drop_collection(nombre)
    preparar(base, json.loads(RUTA_ESQUEMA.read_text(encoding="utf-8")))
    yield base
    base.client.close()


COLECCION_PRUEBAS = "ofertas_pruebas"


@pytest.fixture(scope="session")
def params_bc(params_bow) -> Parametros:
    """La base de conocimiento de las pruebas usa su propia colección de Qdrant. Sin umbrales:
    los de producción están calibrados para e5, no para el embebedor de palabras."""
    bc = params_bow.base_conocimiento.model_copy(
        update={
            "coleccion": COLECCION_PRUEBAS,
            "umbral_relevancia": {"titulo": 0.0, "competencias": 0.0, "fragmentos": 0.0},
        }
    )
    return params_bow.model_copy(update={"base_conocimiento": bc})


@pytest.fixture
def qdrant():
    """Cliente de Qdrant real; la colección de pruebas se borra antes y después."""
    from ingesta.servicios import conectar_qdrant

    cliente = conectar_qdrant()
    cliente.delete_collection(COLECCION_PRUEBAS)
    yield cliente
    cliente.delete_collection(COLECCION_PRUEBAS)
    cliente.close()


DOMINGO = datetime(2026, 9, 27, 15, 0, tzinfo=UTC)  # 10:00 en Lima


@pytest.fixture
def dep(bd, params_bow, nlp, tmp_path):
    """Constructor de dependencias de prueba: MongoDB real, embebedor de palabras, reloj falso."""
    from ingesta.campana import Dependencias

    from .utiles import EmbebedorPalabras, RelojFalso, vocab_prueba

    def construir(ahora=DOMINGO, params=params_bow, vocab=None):
        reloj = RelojFalso()
        return Dependencias(
            bd=bd,
            params=params,
            vocab=vocab or vocab_prueba(),
            nlp=nlp,
            embebedor=EmbebedorPalabras(),
            reloj=reloj,
            dormir=reloj.dormir,
            ahora=lambda: ahora,
            dir_logs=tmp_path / "logs",
            modelo="embebedor-de-palabras (pruebas)",
        )

    return construir
