"""CP-27 y armado de la lista de competencias para el esquema de R 1.4."""

import pytest

from ingesta.extraccion.extractor import Extractor
from ingesta.extraccion.literal import ComparadorLiteral
from ingesta.extraccion.semantica import ComparadorSemantico
from ingesta.normalizacion import SECCION_EXCLUIDA, Unidad, segmentar
from ingesta.vocabulario import Vocabulario

from .utiles import EmbebedorPalabras


@pytest.fixture
def extractor(vocab, nlp, params):
    literal = ComparadorLiteral(vocab, nlp, params.extraccion.terminos_con_contexto)
    semantico = ComparadorSemantico(vocab, EmbebedorPalabras(), "query: ", 0.65, 0.5)
    semantico.preparar()
    return Extractor(nlp, literal, semantico, vocab, params.nivel_requerido)


def test_cp27_el_tipo_sale_de_la_rama_y_no_de_la_seccion(extractor):
    unidades = [
        Unidad("Trabajo en equipo", "Conocimientos y Certificaciones Indispensables"),
        Unidad("Python avanzado", "Habilidades Blandas"),
    ]
    r = extractor.extraer(unidades)
    tipos = {c["nombre"]: c["tipo"] for c in r.competencias}
    assert tipos == {"Trabajo en equipo": "transversal", "Python": "técnica"}


def test_competencias_sin_duplicados_y_con_el_nivel_encontrado(extractor):
    unidades = [Unidad("Manejo de Python"), Unidad("Python avanzado"), Unidad("Git")]
    r = extractor.extraer(unidades)
    assert r.competencias == [
        {
            "nombre": "Python",
            "categoria": "Lenguajes de programación",
            "tipo": "técnica",
            "nivel_requerido": "avanzado",
        },
        {"nombre": "Git", "categoria": "Control de versiones y CI/CD", "tipo": "técnica"},
    ]


def test_la_via_semantica_solo_actua_sobre_unidades_sin_coincidencia_literal(extractor):
    unidades = [Unidad("Docker y backups"), Unidad("Realizar backups")]
    r = extractor.extraer(unidades)
    assert {c.unidad for c in r.semanticas} == {1}
    assert {c["nombre"] for c in r.competencias} == {"Docker", "Alta disponibilidad"}


def test_expone_las_tecnicas_literales_para_el_filtro(extractor):
    r = extractor.extraer(
        [Unidad("SQL Server, Python y trabajo colaborativo"), Unidad("Realizar backups")]
    )
    assert r.tecnicas_literales() == {"SQL Server", "Python"}


def test_el_nivel_de_una_seccion_no_se_atribuye_al_cargo_de_la_seccion_anterior(nlp, params):
    """Aviso 1118454695 de Bumeran: «Dominio» abre Conocimientos técnicos y califica el SIEM;
    «SOC» solo aparece en la experiencia previa y no tiene marcador propio."""
    vocab = Vocabulario(
        {
            "version": 1,
            "categorias": {"Seguridad": "técnica"},
            "terminos": [
                {"nombre": n, "categoria": "Seguridad", "literales": [], "descriptivas": []}
                for n in ("SOC", "SIEM")
            ],
        }
    )
    detalle = (
        "Experiencia mínima de dos (02) años desempeñando funciones como Analista SOC (L1/L2), "
        "Analista NOC con enfoque en seguridad o especialista en análisis de logs y "
        "vulnerabilidades.CONOCIMIENTOS TÉCNICOS Dominio en la instalación, configuración y "
        "afinación de plataformas SIEM/EDR de código abierto (Wazuh, Elastic Security, Graylog) "
        "y sistemas IDS/IPS / deseable."
    )
    literal = ComparadorLiteral(vocab, nlp, params.extraccion.terminos_con_contexto)
    extractor = Extractor(nlp, literal, None, vocab, params.nivel_requerido)
    r = extractor.extraer(segmentar(detalle, "Bumeran"))
    niveles = {c["nombre"]: c.get("nivel_requerido") for c in r.competencias}
    assert niveles["SOC"] is None
    assert niveles["SIEM"] == "avanzado"


def test_sin_via_semantica_solo_extrae_por_diccionario(vocab, nlp, params):
    literal = ComparadorLiteral(vocab, nlp, params.extraccion.terminos_con_contexto)
    extractor = Extractor(nlp, literal, None, vocab, params.nivel_requerido)
    r = extractor.extraer([Unidad("Docker"), Unidad("Realizar backups")])
    assert [c["nombre"] for c in r.competencias] == ["Docker"]
    assert r.semanticas == [] and r.candidatos == []


def test_la_via_semantica_ignora_beneficios_y_empresa(extractor):
    r = extractor.extraer([Unidad("Realizar backups", SECCION_EXCLUIDA)])
    assert r.semanticas == [] and r.candidatos == []


def test_el_diccionario_sigue_actuando_en_beneficios_y_empresa(extractor):
    r = extractor.extraer([Unidad("Capacitación en Docker", SECCION_EXCLUIDA)])
    assert [c["nombre"] for c in r.competencias] == ["Docker"]
