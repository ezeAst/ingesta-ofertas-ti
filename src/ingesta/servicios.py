"""Armado de las dependencias reales (MongoDB, TEI, spaCy); lo comparten la CLI y el panel."""

import json
import warnings

from pymongo.database import Database

from ingesta.bd import conectar, preparar
from ingesta.campana import Dependencias
from ingesta.config import DIR_VOCABULARIO, RUTA_ESQUEMA, Entorno, cargar_parametros
from ingesta.embeddings import ClienteTEI
from ingesta.vocabulario import Vocabulario


def conectar_bd() -> Database:
    bd = conectar(Entorno())
    preparar(bd, json.loads(RUTA_ESQUEMA.read_text(encoding="utf-8")))
    return bd


def conectar_qdrant():
    from qdrant_client import QdrantClient

    entorno = Entorno()
    # La clave viaja por http sin cifrar, pero solo dentro de la red de Docker o hacia 127.0.0.1
    # (I17): el aviso de qdrant-client no aplica.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", "Api key is used with an insecure connection")
        return QdrantClient(url=entorno.qdrant_url, api_key=entorno.qdrant_api_key, timeout=10)


def descripcion_modelo(tei: ClienteTEI) -> str:
    info = tei.info()
    return (
        f"{info.get('model_id')}@{info.get('model_sha')} "
        f"(TEI {info.get('version')}, {info.get('model_dtype')})"
    )


def construir_dependencias(bd: Database, nlp=None, tei: ClienteTEI | None = None) -> Dependencias:
    """El vocabulario y los parámetros se leen siempre de disco: así se usa la versión vigente."""
    if nlp is None:
        import spacy

        nlp = spacy.load("es_core_news_md")
    tei = tei or ClienteTEI(Entorno().embeddings_url)
    return Dependencias(
        bd=bd,
        params=cargar_parametros(),
        vocab=Vocabulario.cargar_vigente(DIR_VOCABULARIO),
        nlp=nlp,
        embebedor=tei,
        modelo=descripcion_modelo(tei),
    )
