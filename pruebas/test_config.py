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
