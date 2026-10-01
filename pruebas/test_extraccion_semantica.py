"""CP-25 (unitaria): vía semántica con umbral y cola de candidatos."""

import pytest

from ingesta.extraccion.semantica import ComparadorSemantico, _tramos

from .utiles import EmbebedorPalabras


@pytest.fixture
def semantico(vocab):
    s = ComparadorSemantico(
        vocab, EmbebedorPalabras(), "query: ", umbral=0.65, umbral_candidato=0.5
    )
    s.preparar()
    return s


def test_cp25_sobre_el_umbral_acepta_la_competencia(semantico, nlp):
    docs = [nlp("Realizar backups")]
    aceptadas, candidatos = semantico.evaluar(docs, [0])
    assert [a.termino for a in aceptadas] == ["Alta disponibilidad"]
    assert aceptadas[0].via == "semantica"
    assert aceptadas[0].puntaje >= 0.65
    assert candidatos == []


def test_cp25_entre_umbrales_se_encola_como_candidato(semantico, nlp):
    docs = [nlp("Infraestructura en la nube")]
    aceptadas, candidatos = semantico.evaluar(docs, [0])
    assert aceptadas == []
    assert len(candidatos) == 1
    c = candidatos[0]
    assert c.termino_cercano == "Infraestructura como código"
    assert 0.5 <= c.puntaje < 0.65
    assert c.unidad == "Infraestructura en la nube"
    assert c.tramo


def test_bajo_el_umbral_de_candidato_no_se_encola(semantico, nlp):
    aceptadas, candidatos = semantico.evaluar([nlp("Sueldo competitivo")], [0])
    assert aceptadas == [] and candidatos == []


def test_solo_evalua_las_unidades_indicadas(semantico, nlp):
    docs = [nlp("Realizar backups"), nlp("Realizar backups")]
    aceptadas, _ = semantico.evaluar(docs, [1])
    assert [a.unidad for a in aceptadas] == [1]


def test_solo_compara_con_variantes_descriptivas(semantico, nlp):
    # «Pensamiento analítico» es un término canónico sin descriptivas: no es objetivo semántico.
    aceptadas, candidatos = semantico.evaluar([nlp("Pensamiento analítico")], [0])
    assert aceptadas == [] and candidatos == []
    assert {texto for texto, _ in semantico._objetivos} == {
        "orquestación de contenedores",
        "backups",
        "infraestructura declarativa versionada",
    }


def test_vocabulario_sin_descriptivas_no_consulta_tramos(nlp):
    from ingesta.vocabulario import Vocabulario

    vocab = Vocabulario(
        {
            "version": 1,
            "categorias": {"Bases de datos": "técnica"},
            "terminos": [
                {
                    "nombre": "SQL",
                    "categoria": "Bases de datos",
                    "literales": [],
                    "descriptivas": [],
                }
            ],
        }
    )
    emb = EmbebedorPalabras()
    s = ComparadorSemantico(vocab, emb, "query: ", umbral=0.65, umbral_candidato=0.5)
    s.preparar()
    assert s.evaluar([nlp("SQL")], [0]) == ([], [])
    assert len(emb.llamadas) == 0


def test_usa_el_prefijo_e5_en_objetivos_y_tramos(vocab, nlp):
    emb = EmbebedorPalabras()
    s = ComparadorSemantico(vocab, emb, "query: ", umbral=0.65, umbral_candidato=0.5)
    s.preparar()
    s.evaluar([nlp("Realizar backups")], [0])
    assert all(t.startswith("query: ") for llamada in emb.llamadas for t in llamada)


FRASE_LARGA = "Coordinar backups con proveedores externos del área de sistemas"


def test_los_grupos_nominales_cortos_no_se_comparan(nlp):
    doc = nlp(FRASE_LARGA)
    assert "backups" in [t for t, _, _ in _tramos(doc, 1)]
    tramos = _tramos(doc, 4)
    assert (FRASE_LARGA, 0, len(FRASE_LARGA)) in tramos  # la unidad completa siempre se compara
    assert all(len(t.split()) >= 4 for t, _, _ in tramos)


def test_con_minimo_de_palabras_un_grupo_corto_ya_no_basta_para_aceptar(vocab, nlp):
    def comparador(minimo):
        s = ComparadorSemantico(
            vocab, EmbebedorPalabras(), "query: ", 0.65, 0.5, min_palabras_tramo=minimo
        )
        s.preparar()
        return s

    aceptadas, _ = comparador(1).evaluar([nlp(FRASE_LARGA)], [0])
    assert [a.termino for a in aceptadas] == ["Alta disponibilidad"]
    assert comparador(4).evaluar([nlp(FRASE_LARGA)], [0]) == ([], [])
