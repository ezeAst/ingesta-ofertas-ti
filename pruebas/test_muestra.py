"""CP-09 (parte automatizada): la muestra exportada no redistribuye el corpus completo."""

import json
from datetime import UTC, datetime

import pytest

from ingesta.almacen import Destinos
from ingesta.muestra import exportar_muestra

pytestmark = pytest.mark.integracion


def _oferta(i: int) -> dict:
    ahora = datetime(2026, 9, 27, tzinfo=UTC)
    return {
        "titulo": f"Oferta {i}",
        "descripcion": "Python y SQL. " * 100,
        "fecha_publicacion": ahora,
        "fuente": {
            "portal": "Bumeran",
            "id_aviso": str(i),
            "url": f"https://x/{i}",
            "fecha_extraccion": ahora,
        },
        "empresa": {"nombre": "ACME"},
        "competencias": [
            {"nombre": "Python", "categoria": "Lenguajes de programación", "tipo": "técnica"}
        ],
    }


def test_cp09_la_muestra_recorta_la_descripcion(bd, tmp_path):
    for i in range(3):
        Destinos(bd).publicar(_oferta(i))
    ruta = exportar_muestra(bd, 2, tmp_path, max_caracteres=300)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert datos["total_en_base"] == 3
    assert len(datos["ofertas"]) == 2
    for oferta in datos["ofertas"]:
        assert "_id" not in oferta
        assert len(oferta["descripcion"]) <= 301
        assert oferta["descripcion"].endswith("…")
        assert oferta["fecha_publicacion"].startswith("2026-09-27")
