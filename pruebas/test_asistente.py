"""Asistente (R 3.4): botones sin LLM, herramientas validadas, reintento acotado, etiquetas de
datos, streaming, brecha y persistencia del turno. Con LLM y búsqueda falsos: no gasta tokens."""

from collections import Counter
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from ingesta.asistente import servicio
from ingesta.asistente.herramientas import Catalogo, validar
from ingesta.asistente.llm import LlamadaHerramienta, RespuestaLLM, Uso
from ingesta.asistente.servicio import (
    BOTON_FALTA,
    BOTON_FUENTES,
    Asistente,
    Busqueda,
    Turno,
    boton_oferta,
    renderizar,
)
from ingesta.config import ParamsAsistente, cargar_parametros
from ingesta.conocimiento.busqueda import OfertaEncontrada, ResultadoBusqueda

CATALOGO = Catalogo(
    competencias=("Go", "Java", "Python", "SQL", "Spring Boot"),
    categorias=("Bases de datos",),
    tipos=("técnica", "transversal"),
    niveles=("básico", "avanzado"),
)
PARAMS = ParamsAsistente()
PARAMS_BC = cargar_parametros().base_conocimiento  # minimo_ofertas = 10


def _oferta(i: int) -> OfertaEncontrada:
    return OfertaEncontrada(
        portal="Bumeran",
        id_aviso=str(i),
        titulo=f"Puesto {i}",
        empresa=f"Empresa {i}",
        url=f"https://x/{i}",
        fecha_publicacion=datetime(2026, 10, 1, tzinfo=UTC),
        puntaje=0.9,
        fragmento=f"Fragmento de la oferta {i}",
        competencias=["Java", "Spring Boot"] if i % 2 == 0 else ["Java", "SQL"],
    )


def _resultado(n: int) -> ResultadoBusqueda:
    ofertas = [_oferta(i) for i in range(1, n + 1)]
    conteo = Counter(c for o in ofertas for c in o.competencias)
    return ResultadoBusqueda(
        ofertas, sorted(conteo.items(), key=lambda p: (-p[1], p[0])), n >= 10, "rrf", None
    )


def _busqueda(n: int = 12) -> Busqueda:
    r = _resultado(n)
    return Busqueda("backend java", {}, r.ofertas, r.conteo, r.suficiente)


class LLMFalso:
    modelo = "falso"

    def __init__(
        self, decision: RespuestaLLM | None = None, redaccion: str = "Piden {{Java}} [1]."
    ):
        self.decision, self.redaccion = decision, redaccion
        self.decisiones: list[list[dict]] = []
        self.redacciones: list[list[dict]] = []

    def completar(self, mensajes, herramientas=None):
        self.decisiones.append(mensajes)
        assert herramientas, "la llamada de decisión debe ofrecer herramientas"
        self.decision.uso = Uso(1000, 50, 0)
        return self.decision

    def completar_stream(self, mensajes, uso):
        self.redacciones.append(mensajes)

        def flujo():
            yield from self.redaccion  # de a un carácter: prueba el corte de marcas
            uso.sumar(Uso(2000, 300, 100))

        return flujo()


def _herramienta(nombre: str, **argumentos) -> RespuestaLLM:
    return RespuestaLLM("", [LlamadaHerramienta(nombre, argumentos)])


@pytest.fixture
def busquedas(monkeypatch):
    """`buscar` falso: ofertas que trae cada consulta (12 por defecto) y registro de llamadas."""
    registro: list[tuple[str, object]] = []
    por_consulta: dict[str, int] = {}

    def falso(bd, qdrant, emb, params, consulta, filtros=None, via=None):
        registro.append((consulta, filtros))
        if filtros is not None and not filtros.vacio() and por_consulta.get("__con_filtros__") == 0:
            return _resultado(0)
        return _resultado(por_consulta.get(consulta, 12))

    monkeypatch.setattr(servicio, "buscar", falso)
    return registro, por_consulta


class ColeccionFalsa:
    def find_one(self, filtro, proyeccion=None):
        return {
            "descripcion": "Descripción completa del aviso " + filtro["fuente.id_aviso"],
            "competencias": [{"nombre": "Java", "nivel_requerido": "avanzado"}],
        }


def _asistente(llm=None) -> Asistente:
    bd = SimpleNamespace(ofertas_laborales=ColeccionFalsa())
    return Asistente(bd, None, None, PARAMS_BC, PARAMS, CATALOGO, llm)


def _completo(a: Asistente, turno: Turno) -> str:
    return (
        "".join(a.transmitir(turno)) if turno.flujo is not None else renderizar(turno.texto, turno)
    )


# --- botones: sin LLM ---------------------------------------------------------------------


def test_boton_fuentes_no_llama_al_llm_y_reutiliza_la_busqueda(busquedas):
    registro, _ = busquedas
    llm = LLMFalso()
    ultima = _busqueda()
    t = _asistente(llm).responder(BOTON_FUENTES, [], ultima)
    assert t.tipo == "fuentes" and t.busqueda is ultima
    assert t.citas == list(range(1, PARAMS.ofertas_en_contexto + 1))
    assert not llm.decisiones and not llm.redacciones and not registro
    assert (t.uso.entrada, t.costo) == (0, 0)


def test_boton_oferta_envia_solo_esa_oferta(busquedas):
    llm = LLMFalso(redaccion="Es un puesto de backend [2] que pide {{Java}}.")
    a = _asistente(llm)
    t = a.responder(boton_oferta(2), [], _busqueda())
    _completo(a, t)
    assert not llm.decisiones and len(llm.redacciones) == 1
    contexto = llm.redacciones[0][-1]["content"]
    assert "Puesto 2" in contexto and "Puesto 1 " not in contexto and "Puesto 3" not in contexto
    assert "Descripción completa del aviso 2" in contexto and "Java (avanzado)" in contexto
    assert t.tipo == "oferta" and t.citas == [2]


def test_boton_oferta_fuera_de_rango():
    t = _asistente(LLMFalso()).responder(boton_oferta(9), [], _busqueda())
    assert t.tipo == "directa" and "No tengo una oferta" in t.texto


def test_boton_falta_pide_las_competencias_sin_llm():
    llm = LLMFalso()
    t = _asistente(llm).responder(BOTON_FALTA, [], _busqueda())
    assert t.tipo == "directa" and "backend java" in t.texto and not llm.decisiones


# --- decisión con herramientas -------------------------------------------------------------


def test_argumentos_fuera_del_catalogo_se_descartan(busquedas):
    registro, _ = busquedas
    decision = _herramienta(
        "buscar_ofertas",
        consulta="backend",
        consulta_alternativa="desarrollo backend",
        competencias_exigidas=["sql", "Inventada", "python", "java", "Go"],
        niveles=["avanzado", "senior"],
        tipos=["técnica"],
    )
    _asistente(LLMFalso(decision)).responder("¿qué piden?", [], None)
    _, filtros = registro[0]
    assert filtros.competencias == ("SQL", "Python", "Java")  # válidas y máximo 3
    assert filtros.niveles == ("avanzado",) and filtros.tipos == ("técnica",)


def test_nivel_sin_competencia_no_se_filtra(busquedas):
    registro, _ = busquedas
    decision = _herramienta(
        "buscar_ofertas", consulta="x", consulta_alternativa="y", niveles=["avanzado"]
    )
    _asistente(LLMFalso(decision)).responder("x", [], None)
    assert registro[0][1].niveles == ()


def test_reintento_con_la_consulta_alternativa(busquedas):
    registro, por_consulta = busquedas
    por_consulta.update({"automatizar despliegues": 2, "DevOps CI/CD": 15})
    decision = _herramienta(
        "buscar_ofertas", consulta="automatizar despliegues", consulta_alternativa="DevOps CI/CD"
    )
    t = _asistente(LLMFalso(decision)).responder("quiero automatizar despliegues", [], None)
    assert [c for c, _ in registro] == ["automatizar despliegues", "DevOps CI/CD"]
    assert t.busqueda.reformulada == "DevOps CI/CD" and len(t.busqueda.ofertas) == 15


def test_reintento_acotado_a_dos_busquedas(busquedas):
    registro, por_consulta = busquedas
    por_consulta.update({"a": 3, "b": 2})
    decision = _herramienta("buscar_ofertas", consulta="a", consulta_alternativa="b")
    t = _asistente(LLMFalso(decision)).responder("a", [], None)
    assert len(registro) == 2 and t.busqueda.reformulada is None and len(t.busqueda.ofertas) == 3


def test_sin_resultados_con_filtros_se_relajan(busquedas):
    registro, por_consulta = busquedas
    por_consulta["__con_filtros__"] = 0
    decision = _herramienta(
        "buscar_ofertas", consulta="a", consulta_alternativa="b", competencias_exigidas=["Java"]
    )
    llm = LLMFalso(decision)
    a = _asistente(llm)
    t = a.responder("a", [], None)
    _completo(a, t)
    assert len(registro) == 3 and registro[2][1].vacio()
    assert t.busqueda.relajada and "se buscó sin filtros" in llm.redacciones[0][-1]["content"]


def test_sin_ofertas_no_se_redacta(busquedas):
    _, por_consulta = busquedas
    por_consulta.update({"cocinero": 0, "chef": 0})
    llm = LLMFalso(_herramienta("buscar_ofertas", consulta="cocinero", consulta_alternativa="chef"))
    t = _asistente(llm).responder("busco trabajo de cocinero", [], None)
    assert "No encontré ofertas" in t.texto and not llm.redacciones and t.flujo is None


def test_respuesta_directa_sin_herramienta(busquedas):
    registro, _ = busquedas
    t = _asistente(LLMFalso(RespuestaLLM("¡Hola! Pregúntame por un puesto."))).responder(
        "hola", [], None
    )
    assert t.tipo == "directa" and t.texto.startswith("¡Hola!") and not registro


def test_herramienta_mostrar_fuentes_no_redacta():
    llm = LLMFalso(_herramienta("mostrar_fuentes"))
    t = _asistente(llm).responder("¿de dónde sacaste eso?", [], _busqueda())
    assert t.tipo == "fuentes" and not llm.redacciones and t.uso.entrada == 1000


def test_decision_recibe_la_ultima_busqueda_y_el_historial_recortado(busquedas):
    llm = LLMFalso(
        _herramienta("buscar_ofertas", consulta="backend java junior", consulta_alternativa="x")
    )
    historial = [{"role": "user", "content": f"m{i} " + "x" * 3000} for i in range(10)]
    _asistente(llm).responder("¿y para junior?", historial, _busqueda())
    mensajes = llm.decisiones[0]
    assert "Última búsqueda" in mensajes[0]["content"] and "backend java" in mensajes[0]["content"]
    assert "[1] Puesto 1 — Empresa 1" in mensajes[0]["content"]
    previos = mensajes[1:-1]
    assert len(previos) == PARAMS.mensajes_de_historial and previos[0]["content"].startswith("m4")
    assert all(len(m["content"]) <= PARAMS.caracteres_por_mensaje for m in previos)


# --- brecha ---------------------------------------------------------------------------------


def test_brecha_resta_lo_conocido(busquedas):
    llm = LLMFalso(
        _herramienta("calcular_brecha", puesto="backend", competencias_conocidas=["java", "Rust"])
    )
    llm.redaccion = "Ya tienes {{Java}}; te piden {{Spring Boot}} y {{SQL}} [1]."
    a = _asistente(llm)
    t = a.responder("sé Java y Rust, ¿qué me falta?", [], None)
    salida = _completo(a, t)
    tiene, falta = t.brecha()
    assert t.tipo == "brecha" and t.conocidas == ["Java"]
    assert [n for n, _ in tiene] == ["Java"] and "Java" not in [n for n, _ in falta]
    assert ":green-badge[Java · 100 %]" in salida and ":orange-badge[SQL · 50 %]" in salida
    assert "TE FALTA" in llm.redacciones[0][-1]["content"]


def test_brecha_sin_competencias_conocidas_las_pide():
    llm = LLMFalso(
        _herramienta("calcular_brecha", puesto="data", competencias_conocidas=["Inventada"])
    )
    t = _asistente(llm).responder("¿qué me falta?", [], None)
    assert t.tipo == "directa" and "Cuéntame qué competencias" in t.texto and not llm.redacciones


# --- etiquetas y streaming ------------------------------------------------------------------


def test_etiquetas_con_el_conteo_real():
    t = Turno("p", "buscar", busqueda=_busqueda(12))
    salida = renderizar("Piden {{java}}, {{ Spring Boot }} y {{Inexistente}} [1] [99] por $10.", t)
    assert ":blue-badge[Java · 100 %]" in salida and ":blue-badge[Spring Boot · 50 %]" in salida
    assert "Inexistente" in salida and "{{" not in salida
    assert ":gray-badge[1]" in salida and "[99]" in salida and r"\$10" in salida


def test_streaming_no_parte_marcas_y_cierra_el_turno(busquedas):
    llm = LLMFalso(_herramienta("buscar_ofertas", consulta="java", consulta_alternativa="jvm"))
    llm.redaccion = "Lo que más piden es {{Java}} y {{Spring Boot}} [1][3]."
    a = _asistente(llm)
    t = a.responder("java", [], None)
    salida = _completo(a, t)
    assert salida == renderizar(llm.redaccion, t)
    assert t.texto == llm.redaccion and t.citas == [1, 3] and t.flujo is None
    assert (t.uso.entrada, t.uso.salida, t.uso.razonamiento) == (3000, 350, 100)
    assert t.costo == pytest.approx((3000 * 0.20 + 350 * 1.20) / 1e6)
    assert t.prompts == ["decision@1", "respuesta@1"]


def test_modo_sin_llm_usa_plantilla_con_etiquetas(busquedas):
    a = _asistente()
    t = a.responder("java", [], None)
    salida = _completo(a, t)
    assert "12 ofertas" in salida and ":blue-badge[Java · 100 %]" in salida and t.uso.entrada == 0


def test_validar_respeta_orden_y_mayusculas():
    assert validar(["sql", "SQL", "go"], CATALOGO.competencias) == ("SQL", "Go")
    assert validar("no es lista", CATALOGO.competencias) == ()


# --- persistencia del turno -----------------------------------------------------------------


def test_turno_ida_y_vuelta_a_documento():
    t = Turno(
        "p",
        "brecha",
        texto="t {{Java}}",
        busqueda=_busqueda(3),
        conocidas=["Java"],
        citas=[1],
        uso=Uso(5, 6, 1),
    )
    copia = Turno.desde_doc(t.a_doc())
    assert (
        copia.busqueda.ofertas == t.busqueda.ofertas and copia.busqueda.conteo == t.busqueda.conteo
    )
    assert (copia.texto, copia.conocidas, copia.citas, copia.uso) == (
        t.texto,
        t.conocidas,
        t.citas,
        t.uso,
    )
