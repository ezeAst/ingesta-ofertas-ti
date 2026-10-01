"""CP-18 y CP-19: deduplicación por clave de bloqueo y similitud de texto (riesgo R4)."""

from datetime import UTC, datetime, timedelta

import pytest

from ingesta.deduplicacion import Deduplicador, jaccard, shingles

DESCRIPCION = (
    "Buscamos analista programador con experiencia en Java y Spring Boot para el equipo de "
    "pagos. Funciones: desarrollo de servicios REST, pruebas unitarias y despliegue en AWS. "
    "Requisitos: bachiller en ingeniería de sistemas y dos años de experiencia."
)
HOY = datetime(2026, 9, 27, tzinfo=UTC)


@pytest.fixture
def dedup(params):
    p = params.deduplicacion
    return Deduplicador(p.ventana_dias, p.tamano_shingle, p.umbral_jaccard)


def _firma(
    dedup,
    portal,
    id_aviso,
    dias=0,
    empresa="ACME S.A.C.",
    titulo="Analista Programador Java",
    descripcion=DESCRIPCION,
):
    return dedup.firma(portal, id_aviso, empresa, titulo, descripcion, HOY + timedelta(days=dias))


def test_jaccard_de_shingles_de_textos_identicos_es_uno():
    assert jaccard(shingles(DESCRIPCION, 5), shingles(DESCRIPCION, 5)) == 1.0


def test_cp18_mismo_aviso_en_otro_portal_es_duplicado(dedup):
    original = _firma(dedup, "Bumeran", "1")
    dedup.registrar(original)
    # Mismo aviso con otro formato: mayúsculas, tildes y espacios distintos.
    copia = _firma(
        dedup,
        "Computrabajo",
        "ABC",
        dias=5,
        empresa="Acme SAC",
        titulo="ANALISTA PROGRAMADOR JAVA",
        descripcion=DESCRIPCION.upper().replace(". ", ".\n"),
    )
    assert dedup.buscar_original(copia) == original


def test_cp19_fuera_de_la_ventana_no_es_duplicado(dedup):
    dedup.registrar(_firma(dedup, "Bumeran", "1"))
    assert dedup.buscar_original(_firma(dedup, "Computrabajo", "ABC", dias=40)) is None


def test_cp19_texto_distinto_no_es_duplicado(dedup):
    dedup.registrar(_firma(dedup, "Bumeran", "1"))
    otra = _firma(
        dedup,
        "Bumeran",
        "2",
        dias=3,
        descripcion="Buscamos analista programador Java para banca. Trabajo presencial en Surco.",
    )
    assert dedup.buscar_original(otra) is None


def test_un_aviso_no_es_duplicado_de_si_mismo(dedup):
    original = _firma(dedup, "Bumeran", "1")
    dedup.registrar(original)
    assert dedup.buscar_original(_firma(dedup, "Bumeran", "1")) is None
