"""Asistente (R 3.4): interpretación validada, citas, filtros relajados y modo sin LLM."""

import json
from datetime import UTC, datetime

import pytest

from ingesta.asistente import servicio
from ingesta.asistente.llm import RespuestaLLM
from ingesta.asistente.servicio import Asistente, Catalogo
from ingesta.conocimiento.busqueda import OfertaEncontrada, ResultadoBusqueda

CATALOGO = Catalogo(
    competencias=("Java", "Python", "Spring Boot"),
    categorias=("Bases de datos",),
    tipos=("técnica", "transversal"),
    niveles=("básico", "avanzado"),
)


def _oferta(n: int) -> OfertaEncontrada:
    return OfertaEncontrada(
        portal="Bumeran",
        id_aviso=str(n),
        titulo=f"Dev {n}",
        empresa="ACME",
        url=f"https://x/{n}",
        fecha_publicacion=datetime(2026, 10, 1, tzinfo=UTC),
        puntaje=0.9,
        fragmento="Java y Spring",
        competencias=["Java", "Spring Boot"],
    )


class LLMFalso:
    """Devuelve primero la interpretación y luego la redacción."""

    def __init__(self, interpretacion: dict, redaccion: str = "Piden Java [1] y Spring [2] [99]."):
        self._respuestas = [json.dumps(interpretacion), redaccion]
        self.llamadas: list[list[dict]] = []

    def completar(self, mensajes, json=False):
        self.llamadas.append(mensajes)
        return RespuestaLLM(self._respuestas[len(self.llamadas) - 1], 10, 5)


@pytest.fixture
def busquedas(monkeypatch):
    registro = []
    respuestas = []

    def falso(bd, qdrant, emb, params, consulta, filtros=None, via=None):
        registro.append((consulta, filtros))
        return respuestas.pop(0)

    monkeypatch.setattr(servicio, "buscar", falso)
    return registro, respuestas


def _resultado(n: int, filtradas=None) -> ResultadoBusqueda:
    ofertas = [_oferta(i) for i in range(1, n + 1)]
    return ResultadoBusqueda(ofertas, [("Java", n)] if n else [], n >= 10, "rrf", filtradas)


def _asistente(llm=None) -> Asistente:
    return Asistente(None, None, None, None, CATALOGO, llm)


def test_interpretacion_descarta_valores_fuera_del_catalogo(busquedas):
    registro, respuestas = busquedas
    respuestas.append(_resultado(12, filtradas=30))
    llm = LLMFalso(
        {
            "accion": "buscar",
            "consulta": "backend java",
            "competencias": ["java", "Inventada"],
            "niveles": ["avanzado", "senior"],
            "tipos": ["técnica"],
        }
    )
    r = _asistente(llm).responder("¿qué piden de Java avanzado?")
    consulta, filtros = registro[0]
    assert consulta == "backend java"
    assert filtros.competencias == ("Java",)
    assert filtros.niveles == ("avanzado",)
    assert filtros.tipos == ("técnica",)
    assert r.con_llm and (r.tokens_entrada, r.tokens_salida) == (20, 10)


def test_citas_solo_de_ofertas_del_contexto(busquedas):
    _, respuestas = busquedas
    respuestas.append(_resultado(12))
    llm = LLMFalso({"accion": "buscar", "consulta": "java"})
    r = _asistente(llm).responder("java")
    assert [n for n, _ in r.citadas] == [1, 2]  # el [99] no existe y se ignora


def test_nivel_sin_competencia_no_se_filtra(busquedas):
    registro, respuestas = busquedas
    respuestas.append(_resultado(12))
    llm = LLMFalso({"accion": "buscar", "consulta": "x", "niveles": ["avanzado"]})
    _asistente(llm).responder("x")
    assert registro[0][1].niveles == ()


def test_filtros_sin_resultados_se_relajan(busquedas):
    registro, respuestas = busquedas
    respuestas += [_resultado(0, filtradas=0), _resultado(11)]
    llm = LLMFalso({"accion": "buscar", "consulta": "java", "competencias": ["Java"]})
    r = _asistente(llm).responder("java")
    assert r.filtros_relajados and len(registro) == 2 and registro[1][1] is None
    assert "se buscó sin filtros" in llm.llamadas[1][-1]["content"]


def test_sin_ofertas_no_llama_al_modelo_para_redactar(busquedas):
    _, respuestas = busquedas
    respuestas.append(_resultado(0))
    llm = LLMFalso({"accion": "buscar", "consulta": "cocina"})
    r = _asistente(llm).responder("receta de cocina")
    assert "No encontré ofertas" in r.texto and len(llm.llamadas) == 1


def test_saludo_se_responde_sin_buscar(busquedas):
    registro, _ = busquedas
    llm = LLMFalso({"accion": "responder", "respuesta_directa": "¡Hola!"})
    r = _asistente(llm).responder("hola")
    assert r.texto == "¡Hola!" and not registro


def test_json_invalido_cae_a_buscar_con_la_pregunta(busquedas):
    registro, respuestas = busquedas
    respuestas.append(_resultado(12))
    llm = LLMFalso({})
    llm._respuestas[0] = "no es json"
    _asistente(llm).responder("pregunta original")
    assert registro[0][0] == "pregunta original"


def test_modo_sin_llm(busquedas):
    _, respuestas = busquedas
    respuestas.append(_resultado(12))
    r = _asistente().responder("java")
    assert not r.con_llm and "12 ofertas" in r.texto and r.citadas == []
