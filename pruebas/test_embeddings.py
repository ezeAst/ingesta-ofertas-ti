"""Cliente del servicio de embeddings (TEI) y CP-25 con el modelo real."""

import json

import httpx
import numpy as np
import pytest
import respx

from ingesta.config import Entorno
from ingesta.embeddings import ClienteTEI
from ingesta.extraccion.semantica import ComparadorSemantico

URL = "http://tei.prueba"


@respx.mock
def test_vectoriza_por_lotes_y_conserva_el_orden():
    def responder(request):
        entradas = json.loads(request.content)["inputs"]
        return httpx.Response(200, json=[[float(len(t)), 0.0] for t in entradas])

    ruta = respx.post(f"{URL}/embed").mock(side_effect=responder)
    textos = [f"t{'x' * i}" for i in range(70)]
    matriz = ClienteTEI(URL, lote=32).vectorizar(textos)
    assert matriz.shape == (70, 2)
    assert [len(json.loads(c.request.content)["inputs"]) for c in ruta.calls] == [32, 32, 6]
    assert matriz[:, 0].tolist() == [float(len(t)) for t in textos]
    cuerpo = json.loads(ruta.calls[0].request.content)
    assert cuerpo["normalize"] is True and cuerpo["truncate"] is True


def test_lista_vacia_no_consulta_el_servicio():
    assert ClienteTEI(URL).vectorizar([]).shape[0] == 0


@pytest.mark.integracion
def test_el_servicio_real_devuelve_vectores_normalizados_de_1024():
    tei = ClienteTEI(Entorno().embeddings_url)
    matriz = tei.vectorizar(["query: Python", "query: Kubernetes"])
    assert matriz.shape == (2, 1024)
    assert np.allclose(np.linalg.norm(matriz, axis=1), 1.0, atol=1e-3)
    assert tei.info()["model_id"] == "intfloat/multilingual-e5-large"


@pytest.mark.integracion
def test_cp25_variante_descriptiva_exacta_supera_el_umbral_de_produccion(vocab, nlp, params):
    ex = params.extraccion
    s = ComparadorSemantico(
        vocab,
        ClienteTEI(Entorno().embeddings_url),
        ex.prefijo_e5,
        ex.umbral_similitud,
        ex.umbral_candidato,
    )
    s.preparar()
    aceptadas, _ = s.evaluar([nlp("Orquestación de contenedores")], [0])
    assert [a.termino for a in aceptadas] == ["Kubernetes"]
    assert aceptadas[0].puntaje >= ex.umbral_similitud


@respx.mock
def test_contar_tokens_por_lotes():
    def responder(request):
        entradas = json.loads(request.content)["inputs"]
        return httpx.Response(200, json=[[{"id": 0}] * len(t) for t in entradas])

    ruta = respx.post(f"{URL}/tokenize").mock(side_effect=responder)
    textos = [f"t{'x' * i}" for i in range(70)]
    conteos = ClienteTEI(URL, lote=32).contar_tokens(textos)
    assert conteos == [len(t) for t in textos]
    assert ruta.call_count == 3


@pytest.mark.integracion
def test_contar_tokens_con_tei_real():
    conteo = ClienteTEI(Entorno().embeddings_url).contar_tokens(["passage: Python"])[0]
    assert 3 <= conteo <= 10
