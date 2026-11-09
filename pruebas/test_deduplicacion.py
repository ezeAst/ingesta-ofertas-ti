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
    return Deduplicador(p.ventana_dias, p.tamano_shingle, p.umbral_jaccard, p.umbral_titulo)


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
    assert dedup.buscar_original(_firma(dedup, "Computrabajo", "ABC", dias=130)) is None


def test_cp49_aviso_republicado_dentro_de_la_ventana_es_duplicado(dedup):
    # Calibración R2.4: las republicaciones llegan hasta 115 días (mediana 49).
    original = _firma(dedup, "Bumeran", "1")
    dedup.registrar(original)
    assert dedup.buscar_original(_firma(dedup, "Bumeran", "2", dias=60)) == original


def test_cp49_titulo_que_cambia_solo_la_ciudad_es_duplicado(dedup):
    original = _firma(
        dedup, "Bumeran", "1", titulo="Soporte Técnico Informático para la ciudad de ANCASH"
    )
    dedup.registrar(original)
    copia = _firma(
        dedup, "Bumeran", "2", titulo="Soporte Técnico Informático para la ciudad de MADRE DE DIOS"
    )
    assert dedup.buscar_original(copia) == original


def test_cp49_misma_plantilla_con_otro_puesto_no_es_duplicado(dedup):
    # Misma empresa y misma descripción, pero el título es de otro puesto.
    dedup.registrar(_firma(dedup, "Bumeran", "1", titulo="QA Automatizador - Exp en AWS"))
    otra = _firma(dedup, "Bumeran", "2", titulo="QA Automatizador - Bantotal")
    assert dedup.buscar_original(otra) is None


def test_otra_empresa_con_el_mismo_texto_no_es_duplicado(dedup):
    dedup.registrar(_firma(dedup, "Bumeran", "1"))
    assert dedup.buscar_original(_firma(dedup, "Bumeran", "2", empresa="Otra S.A.")) is None


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
