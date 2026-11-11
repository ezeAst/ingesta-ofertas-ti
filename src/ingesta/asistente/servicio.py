"""Motor del asistente conversacional (R 3.4), independiente de la interfaz.

Cada mensaje sigue este camino («docs/asistente_criterios_diseno.md»):
1. Los botones de repregunta se resuelven en código, sin LLM.
2. Llamada 1 (decidir): el LLM elige una herramienta (tool calling, V9 de R 2.4) y propone sus
   argumentos; el código los valida contra el vocabulario de R 1.3.
3. El código ejecuta la herramienta. La búsqueda tiene un reintento acotado: si trae menos de
   `minimo_ofertas`, se repite con la consulta alternativa; si sigue en 0 con filtros, se quitan.
4. Llamada 2 (redactar, en streaming) con el contexto que arma el código. El LLM nunca escribe
   cifras: marca {{Competencia}} y el código pone el porcentaje real.

Sin clave de LLM funciona en modo solo recuperación (búsqueda + texto por plantilla).
"""

import re
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from string import Template

from pymongo.database import Database
from qdrant_client import QdrantClient

from ingesta.asistente.herramientas import HERRAMIENTAS, Catalogo, texto, validar
from ingesta.asistente.llm import ClienteLLM, Uso
from ingesta.config import ParamsAsistente, ParamsBaseConocimiento
from ingesta.conocimiento.busqueda import Filtros, OfertaEncontrada, buscar
from ingesta.conocimiento.sincronizacion import EmbebedorConTokens

DIR_PROMPTS = Path(__file__).parent / "prompts"

BOTON_FUENTES = "¿De dónde sale esto?"
BOTON_FALTA = "¿Qué me falta?"
BOTON_JUNIOR = "¿Y para junior?"
_PATRON_BOTON_OFERTA = re.compile(r"^Háblame de la oferta (\d+)$")


def boton_oferta(n: int) -> str:
    return f"Háblame de la oferta {n}"


def cargar_prompt(nombre: str) -> tuple[str, str]:
    """Texto del prompt y su identificador `nombre@versión` (se guarda con cada turno)."""
    contenido = (DIR_PROMPTS / f"{nombre}.md").read_text(encoding="utf-8")
    cabecera = re.match(r"<!--\s*version:\s*(\S+)\s*-->\s*", contenido)
    if not cabecera:
        return contenido, f"{nombre}@?"
    return contenido[cabecera.end() :], f"{nombre}@{cabecera.group(1)}"


# --------------------------------------------------------------------------------------------
# Datos de un turno
# --------------------------------------------------------------------------------------------


@dataclass
class Busqueda:
    consulta: str
    filtros: dict[str, list[str]]
    ofertas: list[OfertaEncontrada]
    conteo: list[tuple[str, int]]
    suficiente: bool
    reformulada: str | None = None  # consulta alternativa que se terminó usando
    relajada: bool = False  # se quitaron los filtros porque no había ofertas

    def porcentajes(self) -> dict[str, int]:
        total = len(self.ofertas)
        return {n: round(100 * c / total) for n, c in self.conteo} if total else {}

    def a_doc(self) -> dict:
        return {**asdict(self), "conteo": [list(par) for par in self.conteo]}

    @classmethod
    def desde_doc(cls, doc: dict) -> "Busqueda":
        return cls(
            consulta=doc["consulta"],
            filtros=doc.get("filtros", {}),
            ofertas=[OfertaEncontrada(**o) for o in doc["ofertas"]],
            conteo=[(n, c) for n, c in doc["conteo"]],
            suficiente=doc["suficiente"],
            reformulada=doc.get("reformulada"),
            relajada=doc.get("relajada", False),
        )


@dataclass
class Turno:
    pregunta: str
    tipo: str  # buscar | brecha | oferta | fuentes | directa
    texto: str = ""  # texto crudo, con marcas {{X}} y citas [n]
    busqueda: Busqueda | None = None
    oferta: int | None = None  # número [n] en «háblame de la oferta n»
    conocidas: list[str] = field(default_factory=list)
    citas: list[int] = field(default_factory=list)
    sugerencias: list[str] = field(default_factory=list)
    uso: Uso = field(default_factory=Uso)
    costo: float = 0.0
    segundos: float = 0.0
    modelo: str = ""
    prompts: list[str] = field(default_factory=list)
    flujo: Iterator[str] | None = None  # texto en streaming; no se guarda
    inicio: float = field(default=0.0, repr=False)  # para medir el tiempo total; no se guarda

    # --- vistas que usa la interfaz ---
    def brecha(self) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
        """(ya lo tiene, le falta), cada lista con su % en las ofertas recuperadas."""
        if not self.busqueda:
            return [], []
        pct = self.busqueda.porcentajes()
        conocidas = {c.casefold() for c in self.conocidas}
        tiene = [(n, p) for n, p in pct.items() if n.casefold() in conocidas]
        falta = [(n, p) for n, p in pct.items() if n.casefold() not in conocidas]
        return tiene, falta

    def a_doc(self) -> dict:
        return {
            "pregunta": self.pregunta,
            "tipo": self.tipo,
            "texto": self.texto,
            "busqueda": self.busqueda.a_doc() if self.busqueda else None,
            "oferta": self.oferta,
            "conocidas": self.conocidas,
            "citas": self.citas,
            "sugerencias": self.sugerencias,
            "tokens": {
                "entrada": self.uso.entrada,
                "salida": self.uso.salida,
                "razonamiento": self.uso.razonamiento,
            },
            "costo_usd": self.costo,
            "segundos": round(self.segundos, 2),
            "modelo": self.modelo,
            "prompts": self.prompts,
        }

    @classmethod
    def desde_doc(cls, doc: dict) -> "Turno":
        tokens = doc.get("tokens") or {}
        return cls(
            pregunta=doc["pregunta"],
            tipo=doc["tipo"],
            texto=doc.get("texto", ""),
            busqueda=Busqueda.desde_doc(doc["busqueda"]) if doc.get("busqueda") else None,
            oferta=doc.get("oferta"),
            conocidas=doc.get("conocidas", []),
            citas=doc.get("citas", []),
            sugerencias=doc.get("sugerencias", []),
            uso=Uso(
                tokens.get("entrada", 0), tokens.get("salida", 0), tokens.get("razonamiento", 0)
            ),
            costo=doc.get("costo_usd", 0.0),
            segundos=doc.get("segundos", 0.0),
            modelo=doc.get("modelo", ""),
            prompts=doc.get("prompts", []),
        )


# --------------------------------------------------------------------------------------------
# Etiquetas de datos: {{X}} → `:blue-badge[X · 74 %]` con el conteo real
# --------------------------------------------------------------------------------------------

_MARCA = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_CITA = re.compile(r"\[(\d{1,2})\]")


def renderizar(crudo: str, turno: Turno) -> str:
    """Markdown para Streamlit: marcas → etiquetas de color con su %, citas → etiquetas grises."""
    pct = turno.busqueda.porcentajes() if turno.busqueda else {}
    por_minuscula = {n.casefold(): n for n in pct}
    conocidas = {c.casefold() for c in turno.conocidas}
    total = len(turno.busqueda.ofertas) if turno.busqueda else 0

    def etiqueta(m: re.Match) -> str:
        nombre = por_minuscula.get(m.group(1).casefold())
        if nombre is None:
            return m.group(1)  # no está en el conteo: queda como texto
        color = "blue"
        if turno.tipo == "brecha":
            color = "green" if nombre.casefold() in conocidas else "orange"
        return f":{color}-badge[{nombre} · {pct[nombre]} %]"

    def cita(m: re.Match) -> str:
        n = int(m.group(1))
        return f":gray-badge[{n}]" if 1 <= n <= total else m.group(0)

    salida = crudo.replace("$", r"\$")  # en Streamlit, $…$ es LaTeX
    salida = _MARCA.sub(etiqueta, salida)
    return _CITA.sub(cita, salida)


def citas_validas(crudo: str, maximo: int) -> list[int]:
    return sorted({int(n) for n in _CITA.findall(crudo)} & set(range(1, maximo + 1)))


def _corte_seguro(pendiente: str) -> int:
    """Hasta dónde se puede mostrar sin partir una marca {{…}} ni una cita […]."""
    corte = len(pendiente)
    for abre, cierra in (("{{", "}}"), ("[", "]")):
        i = pendiente.rfind(abre)
        if i != -1 and cierra not in pendiente[i:]:
            corte = min(corte, i)
    if pendiente.endswith("{"):
        corte = min(corte, len(pendiente) - 1)
    return corte


# --------------------------------------------------------------------------------------------
# Motor
# --------------------------------------------------------------------------------------------


class Asistente:
    def __init__(
        self,
        bd: Database,
        qdrant: QdrantClient,
        embebedor: EmbebedorConTokens,
        params_bc: ParamsBaseConocimiento,
        params: ParamsAsistente,
        catalogo: Catalogo,
        llm: ClienteLLM | None = None,
    ):
        self._bd, self._qdrant, self._embebedor = bd, qdrant, embebedor
        self._pbc, self._p, self._catalogo, self._llm = params_bc, params, catalogo, llm

    @property
    def con_llm(self) -> bool:
        return self._llm is not None

    @property
    def modelo(self) -> str:
        return self._llm.modelo if self._llm else "sin LLM"

    # --- punto de entrada ---
    def responder(self, pregunta: str, historial: list[dict], ultima: Busqueda | None) -> Turno:
        """Prepara el turno. Si `turno.flujo` no es None, la interfaz debe consumir
        `transmitir(turno)`; al agotarse, el turno queda completo (texto, citas, tokens, costo)."""
        inicio = time.perf_counter()
        turno = self._resolver(pregunta.strip(), historial, ultima)
        turno.modelo, turno.inicio = self.modelo, inicio
        if turno.flujo is None:
            self._cerrar(turno)
        return turno

    def transmitir(self, turno: Turno) -> Iterator[str]:
        """Markdown renderizado a medida que llega; las marcas incompletas esperan al resto."""
        crudo, pendiente = [], ""
        for trozo in turno.flujo or ():
            crudo.append(trozo)
            pendiente += trozo
            corte = _corte_seguro(pendiente)
            if corte:
                yield renderizar(pendiente[:corte], turno)
                pendiente = pendiente[corte:]
        if pendiente:
            yield renderizar(pendiente, turno)
        turno.texto = "".join(crudo).strip()
        turno.flujo = None
        self._cerrar(turno)

    def _cerrar(self, turno: Turno) -> None:
        total = len(turno.busqueda.ofertas) if turno.busqueda else 0
        if turno.tipo in ("buscar", "brecha"):
            turno.citas = citas_validas(turno.texto, min(total, self._p.ofertas_en_contexto))
        turno.costo = (
            turno.uso.entrada * self._p.precio_entrada_millon
            + turno.uso.salida * self._p.precio_salida_millon
        ) / 1_000_000
        turno.segundos = time.perf_counter() - turno.inicio

    # --- enrutamiento ---
    def _resolver(self, pregunta: str, historial: list[dict], ultima: Busqueda | None) -> Turno:
        if pregunta == BOTON_FUENTES:
            return self._fuentes(pregunta, ultima)
        if m := _PATRON_BOTON_OFERTA.match(pregunta):
            return self._oferta(pregunta, int(m.group(1)), ultima, historial, Uso(), [])
        if pregunta == BOTON_FALTA:
            return self._pedir_conocidas(pregunta, ultima)
        if not self._llm:
            busqueda = self._buscar_con_reintento(pregunta, "", Filtros())
            return self._redactar_busqueda(pregunta, busqueda, historial, Uso(), [])

        prompt, version = cargar_prompt("decision")
        sistema = Template(prompt).safe_substitute(
            competencias=" | ".join(self._catalogo.competencias),
            categorias=" | ".join(self._catalogo.categorias),
            tipos=" | ".join(self._catalogo.tipos),
            niveles=" | ".join(self._catalogo.niveles),
            ultima_busqueda=self._resumen_ultima(ultima),
        )
        mensajes = [{"role": "system", "content": sistema}, *self._historial(historial)]
        mensajes.append({"role": "user", "content": pregunta})
        decision = self._llm.completar(
            mensajes, HERRAMIENTAS, razonamiento=self._p.razonamiento_decision
        )
        uso, prompts = decision.uso, [version]

        if not decision.llamadas:
            texto_directo = (
                decision.texto or "¿Sobre qué puesto o competencia de TI quieres consultar?"
            )
            return Turno(pregunta, "directa", texto=texto_directo, uso=uso, prompts=prompts)

        llamada = decision.llamadas[0]
        a = llamada.argumentos
        if llamada.nombre == "mostrar_fuentes":
            turno = self._fuentes(pregunta, ultima)
            turno.uso, turno.prompts = uso, prompts
            return turno
        if llamada.nombre == "ver_oferta":
            numero = a.get("numero")
            numero = (
                int(numero)
                if isinstance(numero, int | float | str) and str(numero).isdigit()
                else 0
            )
            return self._oferta(pregunta, numero, ultima, historial, uso, prompts)
        if llamada.nombre == "calcular_brecha":
            conocidas = list(validar(a.get("competencias_conocidas"), self._catalogo.competencias))
            puesto = texto(a.get("puesto")) or (ultima.consulta if ultima else pregunta)
            if not conocidas:
                turno = self._pedir_conocidas(pregunta, ultima)
                turno.uso, turno.prompts = uso, prompts
                return turno
            busqueda = self._buscar_con_reintento(puesto, "", Filtros())
            return self._redactar_brecha(
                pregunta, puesto, conocidas, busqueda, historial, uso, prompts
            )

        # buscar_ofertas (también si el nombre no se reconoce)
        competencias = validar(
            a.get("competencias_exigidas"), self._catalogo.competencias, maximo=3
        )
        filtros = Filtros(
            competencias=competencias,
            categorias=validar(a.get("categorias"), self._catalogo.categorias),
            tipos=validar(a.get("tipos"), self._catalogo.tipos),
            # El nivel es por competencia: solo tiene sentido junto con una competencia exigida.
            niveles=validar(a.get("niveles"), self._catalogo.niveles) if competencias else (),
        )
        consulta = texto(a.get("consulta")) or pregunta
        busqueda = self._buscar_con_reintento(
            consulta, texto(a.get("consulta_alternativa")), filtros
        )
        return self._redactar_busqueda(pregunta, busqueda, historial, uso, prompts)

    # --- búsqueda con reintento acotado ---
    def _buscar(self, consulta: str, filtros: Filtros):
        return buscar(self._bd, self._qdrant, self._embebedor, self._pbc, consulta, filtros)

    def _buscar_con_reintento(self, consulta: str, alternativa: str, filtros: Filtros) -> Busqueda:
        r = self._buscar(consulta, filtros)
        reformulada = None
        if (
            len(r.ofertas) < self._pbc.minimo_ofertas
            and alternativa
            and alternativa.casefold() != consulta.casefold()
        ):
            r2 = self._buscar(alternativa, filtros)
            if len(r2.ofertas) > len(r.ofertas):
                r, reformulada = r2, alternativa
        relajada = False
        if not r.ofertas and not filtros.vacio():
            r, relajada = self._buscar(reformulada or consulta, Filtros()), True
        return Busqueda(
            consulta=consulta,
            filtros={
                k: list(v)
                for k, v in (
                    ("competencias", filtros.competencias),
                    ("categorias", filtros.categorias),
                    ("tipos", filtros.tipos),
                    ("niveles", filtros.niveles),
                )
                if v
            },
            ofertas=r.ofertas,
            conteo=r.conteo,
            suficiente=r.suficiente,
            reformulada=reformulada,
            relajada=relajada,
        )

    # --- cada tipo de turno ---
    def _redactar_busqueda(self, pregunta, b: Busqueda, historial, uso, prompts) -> Turno:
        turno = Turno(pregunta, "buscar", busqueda=b, uso=uso, prompts=prompts)
        if not b.ofertas:
            turno.texto = (
                "No encontré ofertas de TI relacionadas con eso en la base actual. Prueba con un "
                "puesto, unas funciones o una tecnología, por ejemplo «¿qué piden para analista de "
                "datos?» o «me gusta proteger sistemas»."
            )
            return turno
        turno.sugerencias = [BOTON_FUENTES, boton_oferta(1), BOTON_FALTA]
        if not self._llm:
            turno.texto = self._plantilla_busqueda(b)
            return turno
        prompt, version = cargar_prompt("respuesta")
        turno.prompts.append(version)
        turno.flujo = self._redactar(
            self._mensajes_redaccion(
                prompt, historial, self._contexto_busqueda(pregunta, b), pregunta
            ),
            turno.uso,
        )
        return turno

    def _redactar_brecha(
        self, pregunta, puesto, conocidas, b: Busqueda, historial, uso, prompts
    ) -> Turno:
        turno = Turno(pregunta, "brecha", busqueda=b, conocidas=conocidas, uso=uso, prompts=prompts)
        if not b.ofertas:
            turno.tipo, turno.texto = (
                "directa",
                f"No encontré ofertas de «{puesto}» para comparar. ¿Puedes nombrar el puesto de otra forma?",
            )
            return turno
        turno.sugerencias = [BOTON_FUENTES, boton_oferta(1)]
        prompt, version = cargar_prompt("brecha")
        turno.prompts.append(version)
        turno.flujo = self._redactar(
            self._mensajes_redaccion(
                prompt, historial, self._contexto_brecha(puesto, turno), pregunta
            ),
            turno.uso,
        )
        return turno

    def _oferta(self, pregunta, numero, ultima: Busqueda | None, historial, uso, prompts) -> Turno:
        if not ultima or not 1 <= numero <= min(len(ultima.ofertas), self._p.ofertas_en_contexto):
            return Turno(
                pregunta,
                "directa",
                texto="No tengo una oferta con ese número en la última respuesta. Pregúntame primero por un puesto o una competencia.",
                uso=uso,
                prompts=prompts,
            )
        o = ultima.ofertas[numero - 1]
        turno = Turno(
            pregunta,
            "oferta",
            busqueda=ultima,
            oferta=numero,
            citas=[numero],
            uso=uso,
            prompts=prompts,
        )
        siguiente = (
            numero + 1 if numero < min(len(ultima.ofertas), self._p.ofertas_en_contexto) else None
        )
        turno.sugerencias = [
            s for s in (boton_oferta(siguiente) if siguiente else None, BOTON_FALTA) if s
        ]
        doc = self._bd.ofertas_laborales.find_one(
            {"fuente.portal": o.portal, "fuente.id_aviso": o.id_aviso},
            {"descripcion": 1, "competencias": 1},
        )
        descripcion = (doc or {}).get("descripcion") or o.fragmento
        if not self._llm:
            nombres = ", ".join(f"{{{{{c}}}}}" for c in o.competencias[:10])
            turno.texto = f"**[{numero}] {o.titulo}** — {o.empresa} ({o.portal}).\n\nCompetencias que pide: {nombres}.\n\n> {' '.join(descripcion.split())[:600]}…"
            return turno
        prompt, version = cargar_prompt("oferta")
        turno.prompts.append(version)
        niveles = {
            c["nombre"]: c.get("nivel_requerido") for c in (doc or {}).get("competencias", [])
        }
        competencias = ", ".join(
            f"{c} ({niveles[c]})" if niveles.get(c) else c for c in o.competencias
        )
        contexto = (
            f"OFERTA [{numero}]: {o.titulo} — {o.empresa} ({o.portal}, {_fecha(o)})\n"
            f"COMPETENCIAS DE LA OFERTA: {competencias}\n"
            f"DESCRIPCIÓN PUBLICADA:\n«{' '.join(descripcion.split())[: self._p.caracteres_descripcion_oferta]}»"
        )
        turno.flujo = self._redactar(
            self._mensajes_redaccion(prompt, historial, contexto, pregunta), turno.uso
        )
        return turno

    def _fuentes(self, pregunta, ultima: Busqueda | None) -> Turno:
        if not ultima or not ultima.ofertas:
            return Turno(
                pregunta,
                "directa",
                texto="Todavía no he buscado ofertas en esta conversación. Pregúntame por un puesto o una competencia y te muestro de dónde sale cada dato.",
            )
        mostradas = min(len(ultima.ofertas), self._p.ofertas_en_contexto)
        aviso = f" Busqué con otras palabras: «{ultima.reformulada}»." if ultima.reformulada else ""
        turno = Turno(
            pregunta,
            "fuentes",
            busqueda=ultima,
            texto=(
                f"Me basé en ofertas laborales reales. Para «{ultima.consulta}» recuperé "
                f"**{len(ultima.ofertas)} ofertas**: los porcentajes salen de contar sus competencias, "
                f"y estas son las {mostradas} más relevantes, que son las que leí para responder.{aviso}"
            ),
            citas=list(range(1, mostradas + 1)),
        )
        turno.sugerencias = [boton_oferta(1), BOTON_FALTA]
        if "junior" not in ultima.consulta.casefold():
            turno.sugerencias.append(BOTON_JUNIOR)
        return turno

    def _pedir_conocidas(self, pregunta, ultima: Busqueda | None) -> Turno:
        if ultima:
            pedido = f"las comparo con lo que piden las ofertas de «{ultima.consulta}»"
        else:
            pedido = "dime también para qué puesto, y las comparo con lo que piden las ofertas"
        return Turno(
            pregunta,
            "directa",
            texto=f"Cuéntame qué competencias ya manejas (por ejemplo, «sé Java, SQL y Git») y {pedido}.",
        )

    def _redactar(self, mensajes: list[dict], uso: Uso) -> Iterator[str]:
        return self._llm.completar_stream(
            mensajes, uso, razonamiento=self._p.razonamiento_redaccion or None
        )

    # --- contexto para el LLM ---
    def _historial(self, historial: list[dict]) -> list[dict]:
        recorte = self._p.caracteres_por_mensaje
        return [
            {"role": m["role"], "content": m["content"][:recorte]}
            for m in historial[-self._p.mensajes_de_historial :]
            if m.get("content")
        ]

    def _mensajes_redaccion(
        self, prompt: str, historial, contexto: str, pregunta: str
    ) -> list[dict]:
        return [
            {"role": "system", "content": prompt},
            *self._historial(historial),
            {
                "role": "user",
                "content": f"CONTEXTO:\n{contexto}\n\nMENSAJE DEL USUARIO: {pregunta}",
            },
        ]

    def _resumen_ultima(self, ultima: Busqueda | None) -> str:
        if not ultima or not ultima.ofertas:
            return "Todavía no hay búsquedas en esta conversación."
        filtros = "; ".join(f"{k}: {', '.join(v)}" for k, v in ultima.filtros.items()) or "ninguno"
        ofertas = "; ".join(
            f"[{i}] {o.titulo} — {o.empresa}"
            for i, o in enumerate(ultima.ofertas[: self._p.ofertas_en_contexto], 1)
        )
        return (
            "Última búsqueda de esta conversación:\n"
            f"- Consulta: {ultima.consulta}\n- Filtros: {filtros}\n- Ofertas mostradas al usuario: {ofertas}"
        )

    def _avisos(self, b: Busqueda) -> list[str]:
        avisos = []
        if b.reformulada:
            avisos.append(
                f"La consulta original trajo pocas ofertas; se buscó también como «{b.reformulada}»."
            )
        if b.relajada:
            avisos.append("Ninguna oferta cumplía los filtros pedidos; se buscó sin filtros.")
        if not b.suficiente:
            avisos.append("La evidencia es escasa: hay pocas ofertas relevantes.")
        return avisos

    def _bloque_ofertas(self, b: Busqueda) -> str:
        p = self._p
        lineas = []
        for i, o in enumerate(b.ofertas[: p.ofertas_en_contexto], 1):
            fragmento = " ".join(o.fragmento.split())[: p.caracteres_fragmento]
            lineas.append(
                f"[{i}] {o.titulo} — {o.empresa} ({o.portal}, {_fecha(o)}). "
                f"Competencias: {', '.join(o.competencias[: p.competencias_por_oferta])}. "
                f"Fragmento: «{fragmento}»"
            )
        return "\n".join(lineas)

    def _contexto_busqueda(self, pregunta: str, b: Busqueda) -> str:
        pct = b.porcentajes()
        top = ", ".join(f"{n} ({pct[n]} %)" for n, _ in b.conteo[: self._p.competencias_en_conteo])
        partes = [
            f"BÚSQUEDA: «{b.consulta}». Ofertas recuperadas: {len(b.ofertas)}.",
            *(f"AVISO: {a}" for a in self._avisos(b)),
            f"COMPETENCIAS MÁS FRECUENTES (calculadas por el sistema sobre las {len(b.ofertas)} ofertas): {top}",
            f"OFERTAS MÁS RELEVANTES:\n{self._bloque_ofertas(b)}",
        ]
        return "\n".join(partes)

    def _contexto_brecha(self, puesto: str, turno: Turno) -> str:
        b = turno.busqueda
        tiene, falta = turno.brecha()
        n = self._p.competencias_en_conteo
        partes = [
            f"PUESTO: «{puesto}». Ofertas recuperadas: {len(b.ofertas)}.",
            *(f"AVISO: {a}" for a in self._avisos(b)),
            f"EL USUARIO DICE MANEJAR: {', '.join(turno.conocidas)}",
            "YA LO TIENES (aparece en las ofertas): "
            + (", ".join(f"{c} ({p} %)" for c, p in tiene) or "ninguna de esas aparece"),
            "TE FALTA (lo piden y no lo mencionó), de más a menos frecuente: "
            + ", ".join(f"{c} ({p} %)" for c, p in falta[:n]),
            f"OFERTAS MÁS RELEVANTES:\n{self._bloque_ofertas(b)}",
        ]
        return "\n".join(partes)

    def _plantilla_busqueda(self, b: Busqueda) -> str:
        top = ", ".join(f"{{{{{n}}}}}" for n, _ in b.conteo[:6])
        partes = [f"_{a}_" for a in self._avisos(b)]
        partes.append(f"Encontré **{len(b.ofertas)} ofertas** relacionadas con «{b.consulta}».")
        partes.append(f"Lo que más se repite en ellas: {top}.")
        partes.append(
            "Abajo tienes las más relevantes. _(Modo sin LLM: falta la clave del modelo.)_"
        )
        return "\n\n".join(partes)


def _fecha(o: OfertaEncontrada) -> str:
    return o.fecha_publicacion.strftime("%d/%m/%Y") if o.fecha_publicacion else "s/f"
