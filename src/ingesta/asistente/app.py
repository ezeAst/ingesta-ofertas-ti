"""Interfaz del asistente (R 3.2): http://localhost:8502.

Solo presenta: la lógica vive en `servicio.py` (motor), `cuentas.py` e `historial.py`.
"""

import streamlit as st

from ingesta.asistente.cuentas import Cuentas, ErrorCuenta
from ingesta.asistente.herramientas import Catalogo
from ingesta.asistente.historial import Historial
from ingesta.asistente.llm import ClienteLLM, ErrorLLM
from ingesta.asistente.servicio import Asistente, Busqueda, Turno, renderizar
from ingesta.config import Entorno, cargar_parametros
from ingesta.embeddings import ClienteTEI
from ingesta.servicios import conectar_bd, conectar_qdrant

EJEMPLOS = [
    ("Por puesto", "¿Qué piden para analista de datos?"),
    ("Por habilidades", "Sé Python y SQL, ¿a qué puedo postular?"),
    ("Por funciones", "Me gusta proteger sistemas y detectar vulnerabilidades"),
    ("Con requisitos", "¿Qué piden en ofertas que exijan SQL y Power BI?"),
    ("Habilidades blandas", "¿Qué habilidades blandas piden en TI?"),
    (
        "Pregunta abierta",
        "Quiero trabajar con inteligencia artificial pero no sé por dónde empezar",
    ),
]

st.set_page_config(page_title="Orientación profesional en TI", page_icon="💼", layout="centered")


@st.cache_resource
def _recursos():
    bd = conectar_bd()
    entorno = Entorno()
    parametros = cargar_parametros()
    llm = (
        ClienteLLM(entorno.llm_api_key, entorno.llm_modelo, entorno.llm_base_url)
        if entorno.llm_api_key
        else None
    )
    asistente = Asistente(
        bd,
        conectar_qdrant(),
        ClienteTEI(entorno.embeddings_url),
        parametros.base_conocimiento,
        parametros.asistente,
        Catalogo.desde_bd(bd),
        llm,
    )
    return bd, parametros.asistente, asistente, Cuentas(bd), Historial(bd)


@st.cache_data(ttl=600)
def _estado_base() -> tuple[int, str]:
    bd = _recursos()[0]
    ultima = bd.ofertas_laborales.find_one(
        {}, {"fuente.fecha_extraccion": 1}, sort=[("fuente.fecha_extraccion", -1)]
    )
    fecha = ultima["fuente"]["fecha_extraccion"].strftime("%d/%m/%Y") if ultima else "—"
    return bd.ofertas_laborales.count_documents({}), fecha


def _md(texto: str) -> str:
    """Texto de un aviso dentro de Markdown: sin enlaces rotos ni LaTeX accidental."""
    return texto.replace("[", "(").replace("]", ")").replace("$", r"\$")


# --------------------------------------------------------------------------------------------
# Estado de la sesión
# --------------------------------------------------------------------------------------------


def _nueva_conversacion() -> None:
    st.session_state.conv_id = None
    st.session_state.turnos = []
    st.session_state.vista = "chat"
    st.session_state.pop("error", None)


def _iniciar_sesion(usuario: dict) -> None:
    st.session_state.clear()
    st.session_state.usuario = usuario
    st.session_state.gasto = {"entrada": 0, "salida": 0, "costo": 0.0}
    _nueva_conversacion()


def _historial_llm(turnos: list[Turno]) -> list[dict]:
    mensajes = []
    for t in turnos:
        mensajes += [
            {"role": "user", "content": t.pregunta},
            {"role": "assistant", "content": t.texto},
        ]
    return mensajes


def _ultima_busqueda(turnos: list[Turno]) -> Busqueda | None:
    return next((t.busqueda for t in reversed(turnos) if t.busqueda and t.busqueda.ofertas), None)


# --------------------------------------------------------------------------------------------
# Pantallas
# --------------------------------------------------------------------------------------------


def pantalla_entrada(cuentas: Cuentas) -> None:
    st.title("💼 Orientación profesional en TI")
    st.write(
        "Pregunta qué piden las empresas para un puesto, una tecnología o unas funciones. "
        "Las respuestas se basan en **ofertas laborales reales** de Bumeran y Computrabajo (Perú), "
        "con los datos y las fuentes a la vista."
    )
    entrar, crear = st.tabs(["Iniciar sesión", "Crear cuenta"])
    with entrar, st.form("entrar"):
        usuario = st.text_input("Usuario")
        clave = st.text_input("Contraseña", type="password")
        if st.form_submit_button("Entrar", type="primary", width="stretch"):
            cuenta = cuentas.autenticar(usuario, clave)
            if cuenta:
                _iniciar_sesion(cuenta)
                st.rerun()
            st.error("Usuario o contraseña incorrectos.")
    with crear, st.form("crear"):
        usuario = st.text_input(
            "Elige un usuario",
            help="3 a 30 caracteres: letras sin tilde, números, punto, guion o guion bajo.",
        )
        clave = st.text_input("Contraseña (mínimo 8 caracteres)", type="password")
        repetida = st.text_input("Repite la contraseña", type="password")
        if st.form_submit_button("Crear cuenta", type="primary", width="stretch"):
            if clave != repetida:
                st.error("Las contraseñas no coinciden.")
            else:
                try:
                    _iniciar_sesion(cuentas.registrar(usuario, clave))
                    st.rerun()
                except ErrorCuenta as e:
                    st.error(str(e))
    st.caption(
        "Solo guardamos tu usuario, tu contraseña protegida con hash, tus conversaciones y las ofertas "
        "que marques. No pedimos correo ni datos personales."
    )


def barra_lateral(asistente: Asistente, historial: Historial) -> None:
    uid = st.session_state.usuario["_id"]
    with st.sidebar:
        st.markdown("### 💼 Orientación en TI")
        st.caption(f"Sesión de **{st.session_state.usuario['usuario']}**")
        if st.button("Nueva conversación", icon=":material/add:", type="primary", width="stretch"):
            _nueva_conversacion()
            st.rerun()
        guardadas = len(historial.claves_guardadas(uid))
        if st.button(f"⭐ Mis ofertas guardadas ({guardadas})", width="stretch"):
            st.session_state.vista = "guardadas"
            st.rerun()

        conversaciones = historial.listar(uid)
        if conversaciones:
            st.markdown("**Conversaciones**")
        for c in conversaciones:
            actual = c["_id"] == st.session_state.conv_id
            col_titulo, col_borrar = st.columns([6, 1], vertical_alignment="center")
            if col_titulo.button(
                c["titulo"],
                key=f"conv-{c['_id']}",
                width="stretch",
                type="secondary" if actual else "tertiary",
            ):
                st.session_state.conv_id = c["_id"]
                st.session_state.turnos = historial.turnos(uid, c["_id"])
                st.session_state.vista = "chat"
                st.session_state.pop("error", None)
                st.rerun()
            if col_borrar.button(
                ":material/delete:",
                key=f"borrar-{c['_id']}",
                type="tertiary",
                help="Borrar conversación",
            ):
                st.session_state.por_borrar = (c["_id"], c["titulo"])
                st.rerun()

        if por_borrar := st.session_state.get("por_borrar"):
            cid, titulo = por_borrar
            st.warning(f"¿Borrar «{_md(titulo)}»? No se puede deshacer.")
            col_si, col_no = st.columns(2)
            if col_si.button("Borrar", type="primary", width="stretch"):
                historial.borrar(uid, cid)
                if cid == st.session_state.conv_id:
                    _nueva_conversacion()
                st.session_state.pop("por_borrar")
                st.rerun()
            if col_no.button("Cancelar", width="stretch"):
                st.session_state.pop("por_borrar")
                st.rerun()

        st.divider()
        g = st.session_state.gasto
        st.caption(
            f"**Consumo de esta sesión:** {g['entrada']:,} tokens de entrada · {g['salida']:,} de salida · "
            f"US$ {g['costo']:.4f}".replace(",", ".")
        )
        if asistente.con_llm:
            st.caption(f"Modelo: {asistente.modelo}")
        else:
            st.warning("Sin clave de LLM: modo solo recuperación (define LLM_API_KEY en .env).")
        total, fecha = _estado_base()
        st.caption(f"{total:,} ofertas · actualizadas al {fecha}".replace(",", "."))
        if st.button("Cerrar sesión", width="stretch"):
            st.session_state.clear()
            st.rerun()


def recuadro_datos(t: Turno, p) -> None:
    b = t.busqueda
    if not b or not b.ofertas or t.tipo == "directa":
        return
    pct = b.porcentajes()
    with st.container(border=True):
        st.markdown("**📊 Datos de las ofertas**")
        st.caption(
            f"Calculado por el sistema sobre {len(b.ofertas)} ofertas recuperadas · no lo genera la IA"
        )
        if t.tipo == "brecha":
            tiene, falta = t.brecha()
            st.markdown(
                "**Ya lo tienes:** "
                + (
                    " ".join(f":green-badge[{n} · {v} %]" for n, v in tiene)
                    or "_ninguna de las que mencionaste aparece en estas ofertas_"
                )
            )
            st.markdown("**Lo piden y no lo mencionaste:**")
            filas = falta[: p.barras_en_recuadro]
        elif t.tipo == "oferta":
            o = b.ofertas[t.oferta - 1]
            st.markdown(f"**Competencias de la oferta {t.oferta}** y cuánto se piden en las demás:")
            filas = sorted(((n, pct[n]) for n in o.competencias if n in pct), key=lambda x: -x[1])[
                : p.barras_en_recuadro
            ]
        else:
            filas = list(pct.items())[: p.barras_en_recuadro]
        for nombre, valor in filas:
            st.progress(valor / 100, text=f"{_md(nombre)} · {valor} %")


def fuentes(t: Turno, indice: int, historial: Historial, p) -> None:
    b = t.busqueda
    if not b or not b.ofertas or t.tipo == "directa":
        return
    if t.tipo == "fuentes":
        numeros = t.citas
    elif t.tipo == "oferta":
        numeros = [t.oferta]
    else:
        numeros = t.citas or list(range(1, min(3, len(b.ofertas)) + 1))
    uid = st.session_state.usuario["_id"]
    guardadas = historial.claves_guardadas(uid)
    st.markdown("**📌 Fuentes**" if t.citas else "**📌 Ofertas más relevantes**")
    for n in numeros:
        o = b.ofertas[n - 1]
        fecha = o.fecha_publicacion.strftime("%d/%m/%Y") if o.fecha_publicacion else "s/f"
        with st.container(border=True):
            col_texto, col_boton = st.columns([8, 1], vertical_alignment="center")
            col_texto.markdown(
                f":gray-badge[{n}] **[{_md(o.titulo)}]({o.url})**  \n{_md(o.empresa)} · {o.portal} · {fecha}"
            )
            col_texto.caption(
                "Pide: " + ", ".join(o.competencias[:8]) + ("…" if len(o.competencias) > 8 else "")
            )
            guardada = (o.portal, o.id_aviso) in guardadas
            if col_boton.button(
                "★" if guardada else "☆",
                key=f"g-{indice}-{n}",
                help="Quitar de guardadas" if guardada else "Guardar oferta",
            ):
                if guardada:
                    historial.quitar_oferta(uid, o.portal, o.id_aviso)
                else:
                    historial.guardar_oferta(uid, o)
                st.rerun()


def sugerencias(t: Turno, indice: int) -> None:
    if not t.sugerencias:
        return
    columnas = st.columns(len(t.sugerencias))
    for j, (columna, texto) in enumerate(zip(columnas, t.sugerencias, strict=True)):
        if columna.button(texto, key=f"s-{indice}-{j}", width="stretch"):
            st.session_state.pendiente = texto
            st.rerun()


def mostrar_turno(t: Turno, indice: int, ultimo: bool, historial: Historial, p) -> None:
    with st.chat_message("user"):
        st.markdown(t.pregunta)
    with st.chat_message("assistant"):
        st.markdown(renderizar(t.texto, t))
        recuadro_datos(t, p)
        fuentes(t, indice, historial, p)
        if ultimo:
            sugerencias(t, indice)


def procesar(pregunta: str, asistente: Asistente, historial: Historial) -> None:
    turnos: list[Turno] = st.session_state.turnos
    with st.chat_message("user"):
        st.markdown(pregunta)
    with st.chat_message("assistant"):
        try:
            with st.spinner("Buscando en las ofertas…"):
                turno = asistente.responder(
                    pregunta, _historial_llm(turnos), _ultima_busqueda(turnos)
                )
            if turno.flujo is not None:
                st.write_stream(asistente.transmitir(turno))
            else:
                st.markdown(renderizar(turno.texto, turno))
        except ErrorLLM as e:
            st.session_state.error = (pregunta, str(e))
            st.rerun()
    uid = st.session_state.usuario["_id"]
    if st.session_state.conv_id is None:
        st.session_state.conv_id = historial.crear(uid, pregunta)
    historial.guardar_turno(uid, st.session_state.conv_id, turno)
    g = st.session_state.gasto
    g["entrada"] += turno.uso.entrada
    g["salida"] += turno.uso.salida
    g["costo"] += turno.costo
    turnos.append(turno)
    st.rerun()


def pantalla_chat(asistente: Asistente, historial: Historial, p) -> None:
    turnos: list[Turno] = st.session_state.turnos
    if not turnos:
        st.markdown("### ¿Qué quieres saber del mercado laboral de TI?")
        st.write(
            "Te respondo con ofertas laborales reales: qué competencias piden, en qué ofertas aparece "
            "cada dato y qué te falta frente a lo que piden. Prueba con una de estas:"
        )
        columnas = st.columns(2)
        for i, (caso, ejemplo) in enumerate(EJEMPLOS):
            with columnas[i % 2]:
                if st.button(f"**{caso}**  \n{ejemplo}", key=f"ej-{i}", width="stretch"):
                    st.session_state.pendiente = ejemplo
                    st.rerun()
    for i, t in enumerate(turnos):
        mostrar_turno(
            t,
            i,
            ultimo=i == len(turnos) - 1 and "error" not in st.session_state,
            historial=historial,
            p=p,
        )

    if "error" in st.session_state:
        pregunta_fallida, mensaje = st.session_state.error
        with st.chat_message("assistant"):
            st.error(
                f"El modelo de lenguaje no respondió, así que este mensaje no se guardó.\n\n`{mensaje}`"
            )
            if st.button("Reintentar", type="primary"):
                st.session_state.pop("error")
                st.session_state.pendiente = pregunta_fallida
                st.rerun()

    pregunta = st.chat_input("Pregunta por un puesto, una tecnología o unas funciones…")
    pregunta = pregunta or st.session_state.pop("pendiente", None)
    if pregunta:
        st.session_state.pop("error", None)
        procesar(pregunta, asistente, historial)


def pantalla_guardadas(historial: Historial) -> None:
    uid = st.session_state.usuario["_id"]
    if st.button("← Volver al chat"):
        st.session_state.vista = "chat"
        st.rerun()
    st.title("⭐ Mis ofertas guardadas")
    ofertas = historial.ofertas_guardadas(uid)
    if not ofertas:
        st.info(
            "Todavía no guardaste ofertas. En el chat, marca ☆ en una fuente para guardarla aquí."
        )
    for d in ofertas:
        fecha = d["fecha_publicacion"].strftime("%d/%m/%Y") if d.get("fecha_publicacion") else "s/f"
        with st.container(border=True):
            col_texto, col_boton = st.columns([8, 2], vertical_alignment="center")
            col_texto.markdown(
                f"**[{_md(d['titulo'])}]({d['url']})**  \n{_md(d['empresa'])} · {d['portal']} · {fecha}"
            )
            col_texto.caption("Pide: " + ", ".join(d.get("competencias", [])[:10]))
            if col_boton.button("Quitar", key=f"q-{d['portal']}-{d['id_aviso']}", width="stretch"):
                historial.quitar_oferta(uid, d["portal"], d["id_aviso"])
                st.rerun()


# --------------------------------------------------------------------------------------------

try:
    _bd, params, asistente, cuentas, historial = _recursos()
except Exception as e:
    st.error(f"No se pudo conectar con los servicios (MongoDB, Qdrant o embeddings): {e}")
    st.stop()

if "usuario" not in st.session_state:
    pantalla_entrada(cuentas)
    st.stop()

barra_lateral(asistente, historial)
if st.session_state.vista == "guardadas":
    pantalla_guardadas(historial)
else:
    pantalla_chat(asistente, historial, params)
