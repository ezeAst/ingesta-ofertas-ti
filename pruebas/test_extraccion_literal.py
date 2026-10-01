"""CP-20 a CP-24: reglas de la vía literal (Anexo J §6)."""

import pytest

from ingesta.extraccion.literal import ComparadorLiteral


@pytest.fixture
def comparador(vocab, nlp, params):
    return ComparadorLiteral(vocab, nlp, params.extraccion.terminos_con_contexto)


def _terminos(comparador, nlp, *textos):
    docs = [nlp.make_doc(t) for t in textos]
    return [c.termino for c in comparador.buscar(docs)]


def test_cp20_prefiere_la_coincidencia_mas_larga(comparador, nlp):
    assert _terminos(comparador, nlp, "Experiencia en SQL Server") == ["SQL Server"]


def test_cp20_respeta_limites_de_palabra(comparador, nlp):
    assert _terminos(comparador, nlp, "Dominio de JavaScript") == ["JavaScript"]


def test_cp21_las_siglas_respetan_mayusculas(comparador, nlp):
    assert _terminos(comparador, nlp, "Consultas sql básicas") == []
    assert _terminos(comparador, nlp, "Consultas SQL básicas") == ["SQL"]


def test_cp21_terminos_cortos_exigen_contexto(comparador, nlp):
    assert _terminos(comparador, nlp, "Área de RRHH") == []
    assert _terminos(comparador, nlp, "Go-live del proyecto en marzo") == []
    assert _terminos(comparador, nlp, "Manejo del lenguaje R") == ["R"]
    assert _terminos(comparador, nlp, "Desarrollo en Go") == ["Go"]
    assert sorted(_terminos(comparador, nlp, "Python, R y SQL")) == ["Python", "R", "SQL"]


def test_cp22_las_variantes_descriptivas_no_se_usan_como_literales(comparador, nlp):
    assert _terminos(comparador, nlp, "Realizar backups semanales") == []


def test_cp23_una_variante_colisionada_genera_las_dos_entradas(comparador, nlp):
    assert sorted(_terminos(comparador, nlp, "Experiencia con EKS")) == ["AWS", "Kubernetes"]


def test_cp24_reconoce_grafias_incorrectas_registradas(comparador, nlp):
    assert sorted(_terminos(comparador, nlp, "Phyton y Postgree")) == ["PostgreSQL", "Python"]


def test_la_coincidencia_conserva_unidad_y_posicion(comparador, nlp):
    docs = [nlp.make_doc("Sin nada"), nlp.make_doc("Se requiere Docker y Git")]
    coincidencias = comparador.buscar(docs)
    docker = next(c for c in coincidencias if c.termino == "Docker")
    assert docker.unidad == 1
    assert docs[1].text[docker.inicio : docker.fin] == "Docker"
    assert docker.via == "literal"
