"""Parámetros de la campaña (config/parametros.toml) y variables de entorno del servicio."""

import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ = Path(__file__).resolve().parents[2]
RUTA_PARAMETROS = RAIZ / "config" / "parametros.toml"
RUTA_ESQUEMA = RAIZ / "esquemas" / "oferta_laboral.schema.json"
DIR_VOCABULARIO = RAIZ / "vocabulario"
DIR_LOGS = RAIZ / "logs"
DIR_EXPORTACIONES = RAIZ / "exportaciones"


class ParamsCampana(BaseModel):
    zona_horaria: str
    dia_permitido: str


class ParamsHTTP(BaseModel):
    espera_minima_s: float
    reintentos: int
    esperas_reintento_s: list[float]
    corte_rechazos_consecutivos: int
    corte_rechazos_acumulados: int
    tiempo_limite_s: float
    user_agent: str


class ParamsCorrida(BaseModel):
    tasa_exito_minima: float


class ParamsBumeran(BaseModel):
    robots: str
    rutas_vigiladas: list[str]
    url_busqueda: str
    tamano_pagina: int
    orden: str
    cabeceras: dict[str, str]
    filtros: list[dict[str, Any]]
    url_sitemap: str
    url_empleos: str


class ParamsComputrabajo(BaseModel):
    robots: str
    rutas_vigiladas: list[str]
    url_listado: str
    patron_id_aviso: str
    max_paginas: int


class ParamsFuentes(BaseModel):
    bumeran: ParamsBumeran
    computrabajo: ParamsComputrabajo


class ParamsFiltroTI(BaseModel):
    minimo_competencias_tecnicas: int


class ParamsDeduplicacion(BaseModel):
    ventana_dias: int
    tamano_shingle: int
    umbral_jaccard: float


class ParamsTerminosContexto(BaseModel):
    terminos: list[str]
    palabras_contexto: list[str]


class ParamsViaLexica(BaseModel):
    usar: bool = True
    zipf_minimo_espanol: float = 1.0
    margen_espanol: float = 0.5
    zipf_maximo_ingles: float = 4.5
    min_avisos: int = 3


class ParamsExtraccion(BaseModel):
    prefijo_e5: str
    umbral_similitud: float
    umbral_candidato: float
    min_palabras_tramo: int
    usar_via_semantica: bool = True
    terminos_con_contexto: ParamsTerminosContexto
    via_lexica: ParamsViaLexica = ParamsViaLexica()


class ParamsNivel(BaseModel):
    distancia_maxima: int
    basico: list[str]
    intermedio: list[str]
    avanzado: list[str]


class ParamsBaseConocimiento(BaseModel):
    coleccion: str
    prefijo_pasaje: str
    prefijo_consulta: str
    max_tokens_fragmento: int
    lote: int
    limite: int
    minimo_ofertas: int
    rrf_k: int
    umbral_relevancia: dict[str, float]


class Parametros(BaseModel):
    campana: ParamsCampana
    http: ParamsHTTP
    corrida: ParamsCorrida
    fuentes: ParamsFuentes
    filtro_ti: ParamsFiltroTI
    deduplicacion: ParamsDeduplicacion
    extraccion: ParamsExtraccion
    nivel_requerido: ParamsNivel
    base_conocimiento: ParamsBaseConocimiento


def cargar_parametros(ruta: Path = RUTA_PARAMETROS) -> Parametros:
    with ruta.open("rb") as archivo:
        return Parametros.model_validate(tomllib.load(archivo))


class Entorno(BaseSettings):
    """Conexiones a los servicios; las define compose.yaml a partir de `.env`."""

    model_config = SettingsConfigDict(extra="ignore")

    mongo_uri: str = "mongodb://localhost:27017"
    mongo_bd: str = "ingesta"
    embeddings_url: str = "http://localhost:8080"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    # compose.yaml monta ../resultados en /resultados, en solo lectura.
    vocabulario_xlsx: Path = Path("/resultados/R1.3_Vocabulario_Controlado (1).xlsx")
