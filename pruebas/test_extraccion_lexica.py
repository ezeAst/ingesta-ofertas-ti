"""Vía léxica: candidatos por descarte (lo que no es vocabulario, ni español, ni inglés común)."""

from datetime import UTC, datetime

import pytest

from ingesta.almacen import ColaCandidatos
from ingesta.candidatos import aprobar, rechazar
from ingesta.config import ParamsViaLexica
from ingesta.extraccion import Candidato
from ingesta.extraccion.extractor import Extractor
from ingesta.extraccion.lexica import ComparadorLexico
from ingesta.extraccion.literal import ComparadorLiteral
from ingesta.normalizacion import SECCION_EXCLUIDA, Unidad
from ingesta.panel.datos import candidatos_embedding, candidatos_lexicos
from ingesta.vocabulario import Vocabulario, guardar_version

from .utiles import VOCAB_PRUEBA


@pytest.fixture
def lexico(vocab):
    return ComparadorLexico(vocab, ParamsViaLexica())


def _tramos(lexico, *textos, seccion=None):
    return [c.tramo for c in lexico.evaluar([Unidad(t, seccion) for t in textos])]


def test_cp42_queda_lo_que_no_es_vocabulario_ni_espanol(lexico):
    assert _tramos(lexico, "Experiencia con AWS Lambda y Terraform, deseable Python") == [
        "Lambda",
        "Terraform",
    ]


def test_cp42_las_palabras_del_espanol_no_son_candidatas_aunque_sean_raras(lexico):
    assert _tramos(lexico, "Bachiller en carreras afines, asegurando la confidencialidad") == []


def test_cp42_el_ingles_comun_no_es_candidato(lexico):
    assert _tramos(lexico, "Strong team skills and experience") == []


def test_cp42_palabras_contiguas_forman_un_tramo(lexico):
    assert _tramos(lexico, "Orquestación con Apache Airflow y Bizagi") == [
        "Apache Airflow",
        "Bizagi",
    ]


def test_cp42_separa_oraciones_pegadas_y_quita_entidades(lexico):
    assert _tramos(lexico, "Manejo de RxJS.Desarrollo de Terraform).Experiencia&#x2714") == [
        "RxJS",
        "Terraform",
    ]


def test_cp42_separa_camelcase_pegado_al_espanol_pero_no_nombres_propios(lexico):
    assert _tramos(lexico, "ScrumExperiencia en Bizagi") == ["Scrum", "Bizagi"]
    assert _tramos(lexico, "PowerShell") == ["PowerShell"]


def test_cp42_ignora_versiones_y_beneficios(lexico):
    assert _tramos(lexico, "Node v18.20.8") == ["Node"]
    assert _tramos(lexico, "Seguro con Bizagi", seccion=SECCION_EXCLUIDA) == []


def test_cp42_un_tramo_por_aviso_aunque_se_repita(lexico):
    candidatos = lexico.evaluar([Unidad("Lambda"), Unidad("lambda y Python")])
    assert [(c.indice, c.tramo, c.origen) for c in candidatos] == [(0, "Lambda", "lexico")]
    assert candidatos[0].termino_cercano is None and candidatos[0].puntaje is None


def test_cp42_el_extractor_suma_los_lexicos_incluso_con_coincidencia_literal(vocab, nlp, params):
    literal = ComparadorLiteral(vocab, nlp, params.extraccion.terminos_con_contexto)
    lexico = ComparadorLexico(vocab, ParamsViaLexica())
    extractor = Extractor(nlp, literal, None, vocab, params.nivel_requerido, lexico)
    r = extractor.extraer([Unidad("AWS Lambda")])
    assert [c["nombre"] for c in r.competencias] == ["AWS"]
    assert [c.tramo for c in r.candidatos] == ["Lambda"]


def _encolar(bd, id_aviso, tramo="Lambda"):
    cola = ColaCandidatos(bd)
    c = Candidato(0, f"Experiencia en {tramo}", tramo, None, None, origen="lexico")
    return cola.encolar("Bumeran", id_aviso, c, 1, datetime.now(UTC))


@pytest.mark.integracion
def test_cp43_el_panel_agrupa_los_lexicos_por_tramo(bd):
    for id_aviso in ("1", "2", "3"):
        _encolar(bd, id_aviso)
    _encolar(bd, "1", "Bizagi")
    grupos = candidatos_lexicos(bd, min_avisos=2)
    assert [(g["tramo"], g["n_avisos"]) for g in grupos] == [("Lambda", 3)]
    assert candidatos_embedding(bd) == []


@pytest.mark.integracion
def test_cp43_rechazar_un_lexico_lo_descarta_en_todo_el_corpus(bd):
    _encolar(bd, "1")
    _encolar(bd, "2", "lambda")
    rechazar(bd, candidatos_lexicos(bd, 1)[0]["_id"])
    assert bd.candidatos_competencia.count_documents({"estado": "rechazado"}) == 2
    assert _encolar(bd, "3") is False  # un aviso nuevo no lo vuelve a encolar


@pytest.mark.integracion
def test_cp43_aprobar_un_lexico_resuelve_todos_sus_avisos(bd, tmp_path):
    carpeta = tmp_path / "vocabulario"
    guardar_version(VOCAB_PRUEBA, carpeta)
    _encolar(bd, "1")
    _encolar(bd, "2")
    grupo = candidatos_lexicos(bd, 1)[0]
    aprobar(
        bd,
        grupo["_id"],
        carpeta,
        nuevo_termino="AWS Lambda",
        categoria="Cloud, Infraestructura y Operaciones",
    )
    assert bd.candidatos_competencia.count_documents({"estado": "aprobado"}) == 2
    assert "Lambda" in Vocabulario.cargar_vigente(carpeta).termino("AWS Lambda")["literales"]
