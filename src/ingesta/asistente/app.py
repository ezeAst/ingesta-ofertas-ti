"""Interfaz de chat del asistente (R 3.2): http://localhost:8502."""

import pandas as pd
import streamlit as st

from ingesta.asistente.llm import ClienteLLM, ErrorLLM
from ingesta.asistente.servicio import Asistente, Catalogo, Respuesta
from ingesta.config import Entorno, cargar_parametros
from ingesta.embeddings import ClienteTEI
from ingesta.servicios import conectar_bd, conectar_qdrant

EJEMPLOS = [
    "¿Qué piden para desarrollador backend con Java?",
    "¿Qué competencias técnicas se piden en ofertas de ciberseguridad?",
    "Quiero trabajar con datos: ¿qué herramientas y habilidades piden?",
    "¿Qué habilidades blandas son las más pedidas en TI?",
    "¿Qué piden para QA y automatización de pruebas?",
]

st.set_page_config(
    page_title="Asistente de orientación profesional en TI", page_icon="💼", layout="wide"
)


@st.cache_resource
def _recursos():
    bd = conectar_bd()
    entorno = Entorno()
    llm = (
        ClienteLLM(entorno.llm_api_key, entorno.llm_modelo, entorno.llm_base_url)
        if entorno.llm_api_key
        else None
    )
    params = cargar_parametros().base_conocimiento
    asistente = Asistente(
        bd,
        conectar_qdrant(),
        ClienteTEI(entorno.embeddings_url),
        params,
        Catalogo.desde_bd(bd),
        llm,
    )
    return asistente, bd, entorno


def _detalle(r: Respuesta) -> None:
    """Ofertas citadas, competencias más pedidas y datos de la búsqueda de una respuesta."""
    if r.conteo and r.ofertas:
        total = len(r.ofertas)
        with st.expander(
            f"📊 Competencias más pedidas en las {total} ofertas recuperadas", expanded=False
        ):
            tabla = pd.DataFrame(
                [(n, round(100 * c / total)) for n, c in r.conteo[:12]],
                columns=["Competencia", "% de ofertas"],
            )
            st.bar_chart(tabla, x="Competencia", y="% de ofertas", horizontal=True)
    mostradas = r.citadas or [(i, o) for i, o in enumerate(r.ofertas[:5], 1)]
    if mostradas:
        titulo = "📌 Ofertas citadas" if r.citadas else "📌 Ofertas más relevantes"
        with st.expander(f"{titulo} ({len(mostradas)})", expanded=bool(r.citadas)):
            for n, o in mostradas:
                fecha = o.fecha_publicacion.strftime("%d/%m/%Y") if o.fecha_publicacion else "s/f"
                st.markdown(f"**[{n}] [{o.titulo}]({o.url})** · {o.empresa} · {o.portal} · {fecha}")
                st.caption("Competencias: " + ", ".join(o.competencias[:12]))
    if (r.interpretacion and r.ofertas) or (r.interpretacion and r.filtradas == 0):
        with st.expander("🔎 Cómo se buscó", expanded=False):
            i = r.interpretacion
            st.markdown(f"- **Consulta:** {i.consulta}")
            st.markdown(
                f"- **Filtros exactos:** {_filtros(i)}"
                + (" _(relajados: no había ofertas con ellos)_" if r.filtros_relajados else "")
            )
            st.markdown(
                f"- **Ofertas recuperadas:** {len(r.ofertas)} (vía {r.via}); evidencia {'suficiente' if r.suficiente else 'insuficiente'}"
            )
            modo = (
                f"{r.tokens_entrada} tokens de entrada, {r.tokens_salida} de salida"
                if r.con_llm
                else "sin LLM"
            )
            st.markdown(f"- **Tiempo:** {r.segundos:.1f} s · {modo}")


def _filtros(i) -> str:
    partes = [
        f"{nombre} = {', '.join(valores)}"
        for nombre, valores in (
            ("competencias", i.competencias),
            ("categorías", i.categorias),
            ("tipos", i.tipos),
            ("niveles", i.niveles),
        )
        if valores
    ]
    return "; ".join(partes) or "ninguno"


try:
    asistente, bd, entorno = _recursos()
except Exception as e:
    st.error(f"No se pudo conectar con los servicios (MongoDB, Qdrant o embeddings): {e}")
    st.stop()

with st.sidebar:
    st.header("💼 Orientación en TI")
    st.write(
        "Responde con **ofertas laborales reales** de Bumeran y Computrabajo (Perú). "
        "Cita las ofertas en las que se basa y los conteos los calcula el código, no el modelo."
    )
    st.metric(
        "Ofertas en la base", f"{bd.ofertas_laborales.count_documents({}):,}".replace(",", ".")
    )
    if asistente.con_llm:
        st.success(f"Modelo: {entorno.llm_modelo}")
    else:
        st.warning("Sin clave de LLM: modo solo recuperación (define LLM_API_KEY en .env).")
    st.subheader("Prueba con")
    for ejemplo in EJEMPLOS:
        if st.button(ejemplo, use_container_width=True):
            st.session_state.pendiente = ejemplo
    if st.button("🗑️ Nueva conversación", use_container_width=True):
        st.session_state.mensajes = []
        st.rerun()

st.title("Asistente de orientación profesional en TI")
st.caption(
    "Pregunta por un puesto o una competencia. Las respuestas se basan solo en ofertas laborales "
    "recuperadas; no son un consejo laboral personalizado."
)

mensajes: list[dict] = st.session_state.setdefault("mensajes", [])
for m in mensajes:
    with st.chat_message(m["rol"]):
        st.markdown(m["texto"])
        if m.get("respuesta"):
            _detalle(m["respuesta"])

pregunta = st.chat_input("Escribe tu pregunta…") or st.session_state.pop("pendiente", None)
if pregunta:
    with st.chat_message("user"):
        st.markdown(pregunta)
    historial = [
        {"role": "user" if m["rol"] == "user" else "assistant", "content": m["texto"]}
        for m in mensajes
    ]
    with st.chat_message("assistant"):
        try:
            with st.spinner("Buscando ofertas y preparando la respuesta…"):
                respuesta = asistente.responder(pregunta, historial)
        except ErrorLLM as e:
            st.error(f"El modelo de lenguaje no respondió: {e}")
            st.stop()
        st.markdown(respuesta.texto)
        _detalle(respuesta)
    mensajes.append({"rol": "user", "texto": pregunta})
    mensajes.append({"rol": "assistant", "texto": respuesta.texto, "respuesta": respuesta})
