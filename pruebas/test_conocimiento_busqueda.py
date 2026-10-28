"""BC-12 a BC-17: recuperación semántica con filtros en MongoDB y fusión RRF en Qdrant
(R 2.4, V7, V9, V13 y V18).

Con el embebedor de palabras, cada oferta sintética gana por un vector distinto: el título
(«Analista de Datos»), las competencias (Java, Docker) o un fragmento de la descripción
(«automatizar despliegues»).
"""

import pytest

from ingesta.conocimiento.busqueda import Filtros, buscar
from ingesta.conocimiento.sincronizacion import sincronizar

from .utiles import EmbebedorPalabras, insertar_oferta

pytestmark = pytest.mark.integracion


class Espia:
    """Delega en el cliente real y anota las búsquedas."""

    def __init__(self, cliente):
        self._cliente = cliente
        self.busquedas = 0
        self.ultima: dict = {}

    def query_points(self, *args, **kwargs):
        self.busquedas += 1
        self.ultima = kwargs
        return self._cliente.query_points(*args, **kwargs)

    def __getattr__(self, nombre):
        return getattr(self._cliente, nombre)


@pytest.fixture
def base(bd, qdrant, params_bc):
    insertar_oferta(
        bd, "A1", "Analista de Datos", "Requisitos: reportes y tableros.", ("Python", "SQL")
    )
    insertar_oferta(
        bd, "A2", "Desarrollador Backend", "Requisitos: servicios web.", ("Java", "Docker")
    )
    insertar_oferta(
        bd,
        "A3",
        "Especialista Cloud",
        "Automatizar despliegues en la nube.\n"
        "Conocimientos y Certificaciones Indispensables:\nCertificación vigente.",
        ("AWS", "Kubernetes"),
        portal="Bumeran",
    )
    embebedor = EmbebedorPalabras()
    p = params_bc.base_conocimiento
    sincronizar(bd, qdrant, embebedor, p)
    espia = Espia(qdrant)

    def consultar(consulta, filtros=None, via=None, p=p):
        return buscar(bd, espia, embebedor, p, consulta, filtros, via)

    consultar.espia = espia
    return consultar


def test_bc12_via_titulo(base):
    r = base("analista de datos", via="titulo")
    assert r.via == "titulo"
    assert r.ofertas[0].titulo == "Analista de Datos"


def test_bc13_via_competencias(base):
    assert base("java docker", via="competencias").ofertas[0].id_aviso == "A2"


def test_bc13_via_fragmentos_y_fragmento_citado(base):
    primera = base("automatizar despliegues", via="fragmentos").ofertas[0]
    assert primera.id_aviso == "A3"
    assert "Automatizar despliegues" in primera.fragmento
    assert "Certificación" not in primera.fragmento


# «analista» solo está en el título de A1; «java», «docker» y «servicios» están en las
# competencias y la descripción de A2. A1 encabeza el vector `titulo` y A2 los otros dos.
CONSULTA_DIVIDIDA = "analista java docker servicios"


def test_bc14_rrf_por_defecto(base):
    assert base(CONSULTA_DIVIDIDA, via="titulo").ofertas[0].id_aviso == "A1"
    assert base(CONSULTA_DIVIDIDA, via="competencias").ofertas[0].id_aviso == "A2"
    assert base(CONSULTA_DIVIDIDA, via="fragmentos").ofertas[0].id_aviso == "A2"
    r = base(CONSULTA_DIVIDIDA)
    assert r.via == "rrf"
    assert r.ofertas[0].id_aviso == "A2"
    assert {o.id_aviso for o in r.ofertas} == {"A1", "A2", "A3"}


def test_bc14_via_invalida_y_consulta_vacia(base):
    with pytest.raises(ValueError):
        base("python", via="empresa")
    with pytest.raises(ValueError):
        base("   ")


def test_bc15_filtros_restringen_en_mongodb(base):
    r = base("analista de datos", Filtros(competencias=("Java",)))
    assert [o.id_aviso for o in r.ofertas] == ["A2"]
    assert r.filtradas == 1


def test_bc15_filtro_sin_ofertas_no_consulta_qdrant(base):
    antes = base.espia.busquedas
    r = base("analista", Filtros(competencias=("Cobol",)))
    assert r.ofertas == []
    assert r.filtradas == 0
    assert base.espia.busquedas == antes


def test_bc16_conteo_y_suficiencia(base):
    r = base("analista de datos python")
    assert dict(r.conteo) == {
        n: 1 for n in ("Python", "SQL", "Java", "Docker", "AWS", "Kubernetes")
    }
    assert r.conteo == sorted(r.conteo, key=lambda par: (-par[1], par[0]))
    assert r.suficiente is False
    assert r.filtradas is None


def test_bc17_umbral_por_vector_corta_dentro_del_prefetch(base, params_bc):
    estricto = params_bc.base_conocimiento.model_copy(
        update={"umbral_relevancia": {"titulo": 0.99, "competencias": 0.99, "fragmentos": 0.99}}
    )
    assert base("zapatos rojos", p=estricto).ofertas == []
    # Con el corte solo en dos vectores, la fusión queda con la lista del tercero (`titulo`):
    # gana A1, aunque sin umbrales gana A2 (BC-14).
    solo_titulo = params_bc.base_conocimiento.model_copy(
        update={"umbral_relevancia": {"titulo": 0.0, "competencias": 0.99, "fragmentos": 0.99}}
    )
    fusion = base(CONSULTA_DIVIDIDA, p=solo_titulo)
    assert [o.id_aviso for o in fusion.ofertas] == [
        o.id_aviso for o in base(CONSULTA_DIVIDIDA, via="titulo").ofertas
    ]
    assert fusion.ofertas[0].id_aviso == "A1"


def test_bc14_la_fusion_usa_el_k_configurado(base, params_bc):
    """Calibración del 2026-10-27: con el k = 2 de Qdrant la fusión rendía menos (P@10 0,81
    frente a 0,86 con k = 60)."""
    base(CONSULTA_DIVIDIDA)
    consulta = base.espia.ultima["query"]
    assert consulta.rrf.k == params_bc.base_conocimiento.rrf_k
