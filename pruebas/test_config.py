from ingesta.config import cargar_parametros


def test_los_parametros_del_toml_se_cargan_y_validan():
    p = cargar_parametros()
    assert p.http.espera_minima_s == 2.0
    assert p.http.esperas_reintento_s == [2, 4, 8]
    assert p.fuentes.bumeran.cabeceras["x-site-id"] == "BMPE"
    assert p.fuentes.bumeran.filtros == [
        {"id": "area", "value": "tecnologia-sistemas-y-telecomunicaciones"}
    ]
    assert p.deduplicacion.umbral_jaccard == 0.80
    assert p.extraccion.umbral_candidato < p.extraccion.umbral_similitud
    assert p.extraccion.umbral_similitud == 0.90
    assert p.extraccion.min_palabras_tramo == 4
    assert "avanzado" in p.nivel_requerido.avanzado
    assert p.nivel_requerido.distancia_maxima > 0


def test_los_parametros_se_pueden_serializar_para_la_ejecucion():
    """Cada ejecución guarda los parámetros usados (Anexo J §9, configuración)."""
    p = cargar_parametros()
    datos = p.model_dump()
    assert datos["corrida"]["tasa_exito_minima"] == 0.5


def test_parametros_de_base_conocimiento():
    """R 2.4, V13: corte de la búsqueda y fragmentos, configurables."""
    bc = cargar_parametros().base_conocimiento
    assert bc.limite == 50
    assert bc.minimo_ofertas == 10
    assert bc.max_tokens_fragmento == 400
    assert bc.prefijo_pasaje == "passage: "
    assert bc.prefijo_consulta == "query: "
    # Calibración del 2026-10-27 («R 2.4 - Calibracion inicial.md»).
    assert bc.umbral_relevancia == {"titulo": 0.87, "competencias": 0.84, "fragmentos": 0.835}
    assert bc.rrf_k == 60
