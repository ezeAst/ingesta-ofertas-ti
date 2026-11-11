"""Asistente conversacional (R 3.4).

Cada pregunta pasa por tres pasos (diseño de R 2.4, V7 y V18):
1. el LLM interpreta la pregunta: la reescribe como consulta y propone filtros exactos que
   se validan contra el vocabulario controlado (una competencia inventada no llega a MongoDB);
2. `buscar()` recupera las ofertas (MongoDB filtra, Qdrant ordena con RRF) y el código cuenta
   las competencias;
3. el LLM redacta con las ofertas recuperadas y cita [n]; no calcula ningún conteo.

Sin clave de LLM el asistente funciona en modo solo recuperación: la misma búsqueda y un texto
armado por plantilla.
"""

import json
import re
import time
from dataclasses import dataclass, field

from pymongo.database import Database
from qdrant_client import QdrantClient

from ingesta.asistente.llm import ClienteLLM
from ingesta.config import ParamsBaseConocimiento
from ingesta.conocimiento.busqueda import Filtros, OfertaEncontrada, buscar
from ingesta.conocimiento.sincronizacion import EmbebedorConTokens

OFERTAS_EN_CONTEXTO = 8
COMPETENCIAS_EN_CONTEXTO = 15
MENSAJES_DE_HISTORIAL = 6
CARACTERES_FRAGMENTO = 450


@dataclass(frozen=True)
class Catalogo:
    """Valores permitidos para los filtros, tomados de las ofertas publicadas."""

    competencias: tuple[str, ...]
    categorias: tuple[str, ...]
    tipos: tuple[str, ...]
    niveles: tuple[str, ...]

    @classmethod
    def desde_bd(cls, bd: Database) -> "Catalogo":
        ofertas = bd.ofertas_laborales
        return cls(
            competencias=tuple(sorted(ofertas.distinct("competencias.nombre"))),
            categorias=tuple(sorted(ofertas.distinct("competencias.categoria"))),
            tipos=tuple(sorted(ofertas.distinct("competencias.tipo"))),
            niveles=tuple(sorted(ofertas.distinct("competencias.nivel_requerido"))),
        )


@dataclass(frozen=True)
class Interpretacion:
    accion: str  # "buscar" | "responder"
    consulta: str = ""
    competencias: tuple[str, ...] = ()
    categorias: tuple[str, ...] = ()
    tipos: tuple[str, ...] = ()
    niveles: tuple[str, ...] = ()
    respuesta_directa: str = ""


@dataclass
class Respuesta:
    texto: str
    ofertas: list[OfertaEncontrada] = field(default_factory=list)
    citadas: list[tuple[int, OfertaEncontrada]] = field(default_factory=list)
    conteo: list[tuple[str, int]] = field(default_factory=list)
    interpretacion: Interpretacion | None = None
    filtradas: int | None = None
    via: str = ""
    suficiente: bool = True
    filtros_relajados: bool = False
    con_llm: bool = False
    tokens_entrada: int = 0
    tokens_salida: int = 0
    segundos: float = 0.0


def _validar(valores, permitidos: tuple[str, ...]) -> tuple[str, ...]:
    """Deja solo los valores del catálogo (sin distinguir mayúsculas) y sin repetir."""
    if not isinstance(valores, list):
        return ()
    por_minuscula = {p.casefold(): p for p in permitidos}
    salida: list[str] = []
    for v in valores:
        canonico = por_minuscula.get(str(v).strip().casefold())
        if canonico and canonico not in salida:
            salida.append(canonico)
    return tuple(salida)


def _prompt_interpretacion(c: Catalogo) -> str:
    return f"""Eres el módulo de interpretación de un asistente de orientación profesional en TI. \
El asistente responde con ofertas laborales reales del mercado peruano (Bumeran y Computrabajo).

Devuelve SOLO un JSON con estas claves:
- "accion": "buscar" si la pregunta se puede responder con ofertas laborales de TI (roles, \
competencias, requisitos, tendencias, comparaciones, qué aprender para un puesto); "responder" si \
es un saludo, un agradecimiento, una pregunta sobre qué puedes hacer, o algo ajeno al empleo en TI.
- "respuesta_directa": si accion es "responder", tu respuesta breve en español (máximo 3 frases; \
si es ajena a TI, explica con amabilidad que solo orientas con ofertas de TI); si no, "".
- "consulta": si accion es "buscar", una frase de búsqueda en español que describa el puesto o las \
competencias de interés, resolviendo referencias del historial (por ejemplo «y para junior?» \
→ el puesto de antes). Sin signos de pregunta.
- "competencias": nombres EXACTOS de la lista de competencias que la pregunta exige como \
requisito obligatorio (todas deben aparecer en la oferta). Solo las mencionadas de forma explícita; \
si dudas, deja la lista vacía. Máximo 3.
- "categorias": nombres exactos de categorías, solo si la pregunta pide explícitamente un área \
(por ejemplo, «soft skills» → transversal en "tipos", no categorías). Normalmente vacío.
- "tipos": ["técnica"] o ["transversal"] si la pregunta se limita a uno de ellos; si no, [].
- "niveles": ["básico"|"intermedio"|"avanzado"] solo si pide un nivel de dominio de una competencia \
concreta; si no, []. «Junior» o «senior» NO son niveles: ponlos en "consulta".

Competencias: {" | ".join(c.competencias)}
Categorías: {" | ".join(c.categorias)}
Tipos: {" | ".join(c.tipos)}
Niveles: {" | ".join(c.niveles)}"""


PROMPT_RESPUESTA = """Eres un asistente de orientación profesional para estudiantes y egresados de \
ingeniería informática y carreras afines. Respondes SOLO con las ofertas laborales de TI \
recuperadas que se te entregan (mercado peruano, Bumeran y Computrabajo).

Reglas:
- Usa únicamente los datos del contexto. No inventes empresas, sueldos, cifras ni requisitos.
- Cita las ofertas con su número entre corchetes, por ejemplo [2], cuando afirmes algo de ellas.
- Los conteos y porcentajes los calculó el código sobre las ofertas recuperadas: úsalos tal cual \
y aclara que describen esas ofertas, no todo el mercado.
- Si dice que la evidencia es insuficiente o que se relajaron los filtros, adviértelo al inicio.
- No recomiendes cursos ni rutas de aprendizaje: describe lo que piden las ofertas.
- Si el contexto no alcanza para responder, dilo con claridad.
- Español, tono cercano y profesional, entre 120 y 250 palabras, con viñetas cuando ayuden.
- Cierra con una sugerencia breve de qué más podría consultar el usuario."""


def _fecha(o: OfertaEncontrada) -> str:
    return o.fecha_publicacion.strftime("%d/%m/%Y") if o.fecha_publicacion else "s/f"


def _contexto(
    pregunta: str,
    ofertas: list[OfertaEncontrada],
    conteo: list[tuple[str, int]],
    filtradas: int | None,
    suficiente: bool,
    relajado: bool,
) -> str:
    total = len(ofertas)
    lineas = [f"PREGUNTA: {pregunta}", ""]
    estado = f"{total} ofertas recuperadas"
    if filtradas is not None:
        estado += f" (de {filtradas} que cumplían los filtros)"
    lineas.append(
        f"BÚSQUEDA: {estado}. Evidencia suficiente: {'sí' if suficiente else 'NO (pocas ofertas)'}."
    )
    if relajado:
        lineas.append("AVISO: ninguna oferta cumplía los filtros pedidos; se buscó sin filtros.")
    top = ", ".join(
        f"{n} {c} ({round(100 * c / total)} %)" for n, c in conteo[:COMPETENCIAS_EN_CONTEXTO]
    )
    lineas += [
        "",
        f"COMPETENCIAS MÁS FRECUENTES en esas {total} ofertas (conteo del código): {top}",
        "",
    ]
    lineas.append(f"OFERTAS (las {min(total, OFERTAS_EN_CONTEXTO)} más relevantes):")
    for i, o in enumerate(ofertas[:OFERTAS_EN_CONTEXTO], 1):
        fragmento = " ".join(o.fragmento.split())[:CARACTERES_FRAGMENTO]
        lineas.append(
            f"[{i}] {o.titulo} — {o.empresa} ({o.portal}, {_fecha(o)}). "
            f"Competencias: {', '.join(o.competencias[:15])}. Fragmento: «{fragmento}»"
        )
    return "\n".join(lineas)


def _texto_sin_llm(ofertas, conteo, suficiente, relajado) -> str:
    total = len(ofertas)
    top = ", ".join(f"{n} ({round(100 * c / total)} %)" for n, c in conteo[:8])
    partes = []
    if relajado:
        partes.append("_Ninguna oferta cumplía los filtros; se buscó sin ellos._")
    if not suficiente:
        partes.append("_Hay pocas ofertas relevantes: tómalo con cautela._")
    partes.append(f"Encontré **{total} ofertas** relacionadas con tu pregunta.")
    partes.append(f"Las competencias que más aparecen en ellas: {top}.")
    partes.append(
        "Abajo están las ofertas más relevantes. _(Modo sin LLM: falta la clave del modelo.)_"
    )
    return "\n\n".join(partes)


class Asistente:
    def __init__(
        self,
        bd: Database,
        qdrant: QdrantClient,
        embebedor: EmbebedorConTokens,
        params: ParamsBaseConocimiento,
        catalogo: Catalogo,
        llm: ClienteLLM | None = None,
    ):
        self._bd, self._qdrant, self._embebedor = bd, qdrant, embebedor
        self._params, self._catalogo, self._llm = params, catalogo, llm

    @property
    def con_llm(self) -> bool:
        return self._llm is not None

    def responder(self, pregunta: str, historial: list[dict[str, str]] | None = None) -> Respuesta:
        inicio = time.perf_counter()
        historial = (historial or [])[-MENSAJES_DE_HISTORIAL:]
        entrada = salida = 0

        if self._llm:
            interpretacion, e, s = self._interpretar(pregunta, historial)
            entrada, salida = entrada + e, salida + s
        else:
            interpretacion = Interpretacion(accion="buscar", consulta=pregunta)

        if interpretacion.accion == "responder":
            return Respuesta(
                texto=interpretacion.respuesta_directa
                or "¿Sobre qué puesto o competencia quieres consultar?",
                interpretacion=interpretacion,
                con_llm=self.con_llm,
                tokens_entrada=entrada,
                tokens_salida=salida,
                segundos=time.perf_counter() - inicio,
            )

        consulta = interpretacion.consulta or pregunta
        filtros = Filtros(
            competencias=interpretacion.competencias,
            categorias=interpretacion.categorias,
            tipos=interpretacion.tipos,
            # El nivel es por competencia: solo tiene sentido junto con una competencia concreta.
            niveles=interpretacion.niveles if interpretacion.competencias else (),
        )
        resultado = buscar(self._bd, self._qdrant, self._embebedor, self._params, consulta, filtros)
        relajado = False
        if not resultado.ofertas and not filtros.vacio():
            resultado = buscar(self._bd, self._qdrant, self._embebedor, self._params, consulta)
            relajado = True

        respuesta = Respuesta(
            texto="",
            ofertas=resultado.ofertas,
            conteo=resultado.conteo,
            interpretacion=interpretacion,
            filtradas=resultado.filtradas,
            via=resultado.via,
            suficiente=resultado.suficiente,
            filtros_relajados=relajado,
            con_llm=self.con_llm,
        )

        if not resultado.ofertas:
            respuesta.texto = (
                "No encontré ofertas relevantes para esa pregunta en la base actual. "
                "Prueba con un puesto o una tecnología de TI (por ejemplo «desarrollador backend con Java» "
                "o «qué piden en ciberseguridad»)."
            )
        elif self._llm:
            contexto = _contexto(
                consulta if not historial else f"{pregunta} (consulta: {consulta})",
                resultado.ofertas,
                resultado.conteo,
                resultado.filtradas,
                resultado.suficiente,
                relajado,
            )
            mensajes = [{"role": "system", "content": PROMPT_RESPUESTA}, *historial]
            mensajes.append(
                {
                    "role": "user",
                    "content": f"{contexto}\n\nResponde la pregunta del usuario: {pregunta}",
                }
            )
            r = self._llm.completar(mensajes)
            respuesta.texto = r.texto
            entrada, salida = entrada + r.tokens_entrada, salida + r.tokens_salida
        else:
            respuesta.texto = _texto_sin_llm(
                resultado.ofertas, resultado.conteo, resultado.suficiente, relajado
            )

        numeros = sorted(
            {int(n) for n in re.findall(r"\[(\d+)\]", respuesta.texto)}
            & set(range(1, min(len(resultado.ofertas), OFERTAS_EN_CONTEXTO) + 1))
        )
        respuesta.citadas = [(n, resultado.ofertas[n - 1]) for n in numeros]
        respuesta.tokens_entrada, respuesta.tokens_salida = entrada, salida
        respuesta.segundos = time.perf_counter() - inicio
        return respuesta

    def _interpretar(self, pregunta: str, historial: list[dict[str, str]]):
        mensajes = [
            {"role": "system", "content": _prompt_interpretacion(self._catalogo)},
            *historial,
        ]
        mensajes.append({"role": "user", "content": pregunta})
        r = self._llm.completar(mensajes, json=True)
        try:
            datos = json.loads(r.texto)
        except json.JSONDecodeError:
            datos = {}
        if not isinstance(datos, dict):
            datos = {}
        c = self._catalogo
        accion = "responder" if datos.get("accion") == "responder" else "buscar"
        return (
            Interpretacion(
                accion=accion,
                consulta=str(datos.get("consulta") or pregunta).strip(),
                competencias=_validar(datos.get("competencias"), c.competencias)[:3],
                categorias=_validar(datos.get("categorias"), c.categorias),
                tipos=_validar(datos.get("tipos"), c.tipos),
                niveles=_validar(datos.get("niveles"), c.niveles),
                respuesta_directa=str(datos.get("respuesta_directa") or "").strip(),
            ),
            r.tokens_entrada,
            r.tokens_salida,
        )
