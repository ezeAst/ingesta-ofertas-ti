"""Paso del documento crudo de cada portal a un aviso normalizado y a la oferta de R 1.4."""

from datetime import UTC, datetime

from ingesta.avisos import armar_oferta, normalizar_aviso

from .utiles import item_bumeran, jobposting

EXTRACCION = datetime(2026, 9, 27, 15, 0, tzinfo=UTC)


def _crudo(portal, contenido, id_aviso="1", url="https://x/1"):
    return {
        "portal": portal,
        "id_aviso": id_aviso,
        "url": url,
        "contenido": contenido,
        "fecha_extraccion": EXTRACCION,
    }


def test_bumeran_fecha_en_hora_de_lima_y_texto_legible():
    aviso = normalizar_aviso(_crudo("Bumeran", item_bumeran(1)))
    assert aviso.titulo == "Analista Programador"
    assert aviso.fecha_publicacion == datetime(2026, 9, 26, 5, 45, 10, tzinfo=UTC)  # 00:45 en Lima
    assert aviso.empresa == "ACME S.A.C." and aviso.sector is None
    assert "Conocimientos y Certificaciones Indispensables:" in aviso.descripcion
    assert "Python y SQL" in aviso.descripcion.splitlines()


def test_cp48_bumeran_el_titulo_es_la_primera_unidad():
    aviso = normalizar_aviso(_crudo("Bumeran", item_bumeran(1, "Desarrollador Java")))
    assert aviso.unidades[0].texto == "Desarrollador Java"
    assert any(
        u.seccion == "Conocimientos y Certificaciones Indispensables" for u in aviso.unidades
    )


def test_cp30_aviso_confidencial_usa_el_texto_del_portal():
    item = item_bumeran(1, empresa="Confidencial", confidencial=True)
    assert normalizar_aviso(_crudo("Bumeran", item)).empresa == "Confidencial"
    item_vacio = item_bumeran(2, empresa=None, confidencial=True)
    assert normalizar_aviso(_crudo("Bumeran", item_vacio)).empresa == "Confidencial"


def test_computrabajo_desde_el_jobposting():
    aviso = normalizar_aviso(_crudo("Computrabajo", {"jobposting": jobposting()}))
    assert aviso.titulo == "Desarrollador Java"
    assert aviso.descripcion == "Java\nSpring Boot y SQL"
    assert aviso.fecha_publicacion == datetime(2026, 9, 20, 5, 0, tzinfo=UTC)
    assert aviso.empresa == "ACME S.A.C."
    assert aviso.sector == "Servicios Profesionales"


def test_fecha_ilegible_queda_vacia():
    item = item_bumeran(1, fechaHoraPublicacion="ayer", fechaPublicacion=None)
    assert normalizar_aviso(_crudo("Bumeran", item)).fecha_publicacion is None


def test_armar_oferta_sigue_el_esquema_y_omite_lo_vacio():
    aviso = normalizar_aviso(_crudo("Bumeran", item_bumeran(1)))
    competencias = [
        {"nombre": "Python", "categoria": "Lenguajes de programación", "tipo": "técnica"}
    ]
    oferta = armar_oferta(aviso, competencias)
    assert set(oferta) == {
        "titulo",
        "descripcion",
        "fecha_publicacion",
        "fuente",
        "empresa",
        "competencias",
    }
    assert oferta["fuente"] == {
        "portal": "Bumeran",
        "id_aviso": "1",
        "url": "https://x/1",
        "fecha_extraccion": EXTRACCION,
    }
    assert oferta["empresa"] == {"nombre": "ACME S.A.C."}  # sin sector: no se inventa


def test_cp48_los_emojis_no_llegan_a_la_oferta_pero_si_quedan_en_el_crudo():
    item = item_bumeran(1, "🚀 Desarrollador Python", detalle="✅ Python  ✅ SQL")
    crudo = _crudo("Bumeran", item)
    aviso = normalizar_aviso(crudo)
    assert aviso.titulo == "Desarrollador Python"
    assert "✅" not in aviso.descripcion
    assert [u.texto for u in aviso.unidades] == ["Desarrollador Python", "Python", "SQL"]
    assert crudo["contenido"]["titulo"] == "🚀 Desarrollador Python"
