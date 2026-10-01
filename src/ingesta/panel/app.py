"""Panel de gestión del mecanismo de ingesta (R 2.3).

docker compose up -d        →  http://localhost:8501
"""

import csv
import io
import os
import signal
from typing import Any

import streamlit as st

from ingesta.campana import PORTALES
from ingesta.candidatos import aprobar, rechazar
from ingesta.config import DIR_VOCABULARIO, RUTA_PARAMETROS, Entorno, cargar_parametros
from ingesta.embeddings import ClienteTEI
from ingesta.gestion import (
    corrida_en_curso,
    publicar_manual,
    quitar_decision_manual,
    reprocesar_aviso,
)
from ingesta.panel import datos
from ingesta.servicios import conectar_bd, construir_dependencias
from ingesta.vocabulario import (
    Vocabulario,
    agregar_categoria,
    agregar_termino,
    agregar_variante,
    guardar_version,
)

st.set_page_config(page_title="Ingesta · panel", page_icon="🗂️", layout="wide")
st.markdown(
    """
    <style>
      mark.lit {background:#c9f2d0; color:#0b3d17; padding:0 .15em; border-radius:3px}
      mark.sem {background:#ffe5a8; color:#5a3b00; padding:0 .15em; border-radius:3px}
      sup.lit {color:#3fb760; font-size:.7em; margin-left:.15em}
      sup.sem {color:#e0a92e; font-size:.7em; margin-left:.15em}
      .unidad {padding:.25em .5em; border-left:3px solid #d0d7de; margin:.15em 0}
      .seccion {font-size:.75em; color:#6e7781; text-transform:uppercase}
    </style>
    """,
    unsafe_allow_html=True,
)


# --- Recursos compartidos -------------------------------------------------------------------


@st.cache_resource
def _bd():
    return conectar_bd()


@st.cache_resource
def _nlp():
    import spacy

    return spacy.load("es_core_news_md")


@st.cache_resource
def _tei():
    return ClienteTEI(Entorno().embeddings_url)


def _dep():
    return construir_dependencias(_bd(), nlp=_nlp(), tei=_tei())


def _vocab() -> Vocabulario:
    return Vocabulario.cargar_vigente(DIR_VOCABULARIO)


def _aviso(mensaje: str, tipo: str = "success") -> None:
    st.session_state["aviso"] = (tipo, mensaje)


bd = _bd()
datos.recoger_terminados()
if "aviso" in st.session_state:
    tipo, mensaje = st.session_state.pop("aviso")
    getattr(st, tipo)(mensaje)


# --- Barra lateral --------------------------------------------------------------------------

with st.sidebar:
    st.title("Ingesta R 2.3")
    try:
        info = _tei().info()
        st.caption(
            f"Embeddings: {info['model_id']} · {info.get('model_dtype')} · TEI {info.get('version')}"
        )
    except Exception as error:  # el panel sigue funcionando sin TEI, salvo para procesar
        st.error(f"Servicio de embeddings no disponible: {error}")
    vocab = _vocab()
    st.caption(f"Vocabulario v{vocab.version} · {len(vocab.terminos)} términos")
    semantica = cargar_parametros().extraccion.usar_via_semantica
    nueva = st.toggle(
        "Extracción por embeddings",
        value=semantica,
        help="Apagado: solo diccionario (coincidencia literal), sin cola de candidatos. "
        "Se aplica a las próximas corridas y reprocesos, no a lo ya procesado.",
    )
    if nueva != semantica:
        datos.fijar_via_semantica(RUTA_PARAMETROS, nueva)
        _aviso(
            "Extracción por embeddings "
            + ("activada." if nueva else "desactivada: solo diccionario.")
            + " Reprocesa para aplicarlo a los avisos ya ingresados.",
            "info",
        )
        st.rerun()
    st.caption("Modo: " + ("diccionario + embeddings" if semantica else "solo diccionario"))
    for nombre, valor in datos.conteos(bd).items():
        st.metric(nombre.capitalize(), valor)


# --- Detalle de un aviso --------------------------------------------------------------------


def mostrar_detalle(portal: str, id_aviso: str) -> dict[str, Any]:
    d = datos.detalle(bd, portal, id_aviso)
    crudo, traza = d["crudo"], d["traza"] or {}
    if crudo is None:
        st.warning("No hay crudo para este aviso.")
        return d
    estado = (
        "🟢 Publicado"
        if d["oferta"]
        else f"🔴 {datos.ETIQUETA_MOTIVO.get(traza.get('motivo'), 'Descartado')}"
    )
    if traza.get("decision_manual"):
        estado += " · decisión manual"
    st.subheader(traza.get("titulo") or crudo["contenido"].get("titulo", "(sin título)"))
    st.markdown(f"**{portal}** · `{id_aviso}` · {estado} · [ver en el portal]({crudo['url']})")

    entro, leyo, quedo = st.tabs(
        ["1 · Cómo entró", "2 · Cómo se leyó", "3 · Cómo quedó registrado"]
    )
    with entro:
        c1, c2, c3 = st.columns(3)
        c1.metric("Extraído (Lima)", datos.hora_lima(crudo["fecha_extraccion"]))
        c2.metric("Contactos eliminados", crudo.get("contactos_eliminados", 0))
        c3.metric("Huella", crudo["huella"][:12] + "…")
        st.caption(
            "Contenido original tal como lo entregó el canal estructurado (sin datos de contacto)."
        )
        st.json(crudo["contenido"], expanded=False)
    with leyo:
        if not traza:
            st.info(
                "Todavía no tiene traza: se procesó antes de que existiera el registro de trazas. Reprocésalo."
            )
        else:
            st.caption(
                f"Vocabulario v{traza['version_vocabulario']} · procesado {datos.hora_lima(traza['fecha'])} · "
                + (
                    "diccionario + embeddings"
                    if traza.get("via_semantica", True)
                    else "solo diccionario"
                )
                + " · verde = coincidencia literal, ámbar = semántica (con puntaje)"
            )
            for seccion, html in datos.unidades_resaltadas(traza):
                etiqueta = f'<div class="seccion">{seccion}</div>' if seccion else ""
                st.markdown(f'<div class="unidad">{etiqueta}{html}</div>', unsafe_allow_html=True)
            if traza.get("candidatos"):
                st.markdown("**Tramos enviados a la cola de candidatos**")
                st.dataframe(
                    [
                        {
                            "tramo": c["tramo"],
                            "término cercano": c["termino_cercano"],
                            "puntaje": c["puntaje"],
                        }
                        for c in traza["candidatos"]
                    ],
                    hide_index=True,
                )
    with quedo:
        if d["oferta"]:
            st.markdown("**Competencias registradas en `ofertas_laborales`**")
            st.dataframe(d["oferta"]["competencias"], hide_index=True)
            with st.expander("Documento completo (validado contra el esquema de R 1.4)"):
                st.json(d["oferta"])
        elif d["descarte"]:
            st.markdown(f"**Motivo:** {datos.ETIQUETA_MOTIVO.get(d['descarte']['motivo'])}")
            st.json(d["descarte"]["detalle"])
            if traza.get("competencias"):
                st.markdown("**Competencias que sí se extrajeron**")
                st.dataframe(traza["competencias"], hide_index=True)
    return d


def boton_reprocesar(portal: str, id_aviso: str, clave: str) -> None:
    if st.button(
        "🔁 Reprocesar este aviso",
        key=f"rep-{clave}",
        help="Con el vocabulario vigente, sin usar la red",
    ):
        with st.spinner("Reprocesando…"):
            r = reprocesar_aviso(_dep(), portal, id_aviso)
        _aviso(f"Reprocesado: {r.destino} {datos.ETIQUETA_MOTIVO.get(r.motivo, '')}")
        st.rerun()


def seleccion(filas: list[dict], clave: str) -> dict | None:
    evento = st.dataframe(
        filas,
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        key=clave,
    )
    elegidas = evento.selection.rows if evento else []
    return filas[elegidas[0]] if elegidas else None


def acciones(d: dict[str, Any], p: str, i: str, clave: str) -> None:
    """Panel lateral de Ofertas y Descartes: reprocesar, fijar competencias, añadir al diccionario."""
    st.subheader("Acciones")
    traza = d["traza"] or {}
    publicada = d["oferta"] is not None
    with st.container(border=True):
        boton_reprocesar(p, i, clave)
        if traza.get("decision_manual") and st.button(
            "↩️ Quitar decisión manual", key=f"{clave}-quitar-{p}-{i}"
        ):
            quitar_decision_manual(bd, p, i)
            reprocesar_aviso(_dep(), p, i)
            _aviso("Decisión manual quitada; el aviso se decidió de nuevo por las reglas.")
            st.rerun()
        st.markdown("**Corregir competencias a mano**" if publicada else "**Publicar a mano**")
        vocab = _vocab()
        nombres = {t["nombre"] for t in vocab.terminos}
        actuales = (d["oferta"] or {}).get("competencias") if publicada else None
        extraidas = [c["nombre"] for c in (actuales or traza.get("competencias", []))]
        elegidas = st.multiselect(
            "Competencias (del vocabulario vigente)",
            sorted(nombres),
            default=[n for n in extraidas if n in nombres],
            key=f"{clave}-manual-{p}-{i}",
        )
        if st.button(
            "🟢 Publicar con estas competencias",
            disabled=not elegidas,
            key=f"{clave}-publicar-{p}-{i}",
        ):
            try:
                publicar_manual(_dep(), p, i, elegidas)
                _aviso("Publicado a mano. La decisión se respetará en los reprocesos.")
            except ValueError as error:
                _aviso(str(error), "error")
            st.rerun()
    with st.container(border=True):
        st.markdown("**Añadir al diccionario**")
        vocab = _vocab()
        tramos = [c["tramo"] for c in traza.get("candidatos", [])]
        accion = st.radio(
            "Qué añadir",
            ["Variante literal", "Variante descriptiva", "Habilidad nueva", "Categoría nueva"],
            key=f"{clave}-dic-accion-{p}-{i}",
        )
        texto_base = st.selectbox(
            "Tomar un tramo del aviso (opcional)",
            ["", *tramos],
            key=f"{clave}-dic-tramo-{p}-{i}",
        )
        with st.form(f"{clave}-diccionario-{p}-{i}"):
            valor = st.text_input("Texto", value=texto_base)
            categorias = sorted(vocab.datos["categorias"])
            if accion in ("Variante literal", "Variante descriptiva"):
                termino = st.selectbox(
                    "Término canónico", sorted(t["nombre"] for t in vocab.terminos)
                )
            elif accion == "Habilidad nueva":
                categoria = st.selectbox("Categoría", categorias)
            else:
                rama = st.radio("Rama", ["técnica", "transversal"], horizontal=True)
            if st.form_submit_button("💾 Guardar versión nueva del vocabulario"):
                try:
                    if not valor.strip():
                        raise ValueError("el texto está vacío")
                    base = vocab.datos
                    if accion == "Variante literal":
                        nuevo = agregar_variante(base, termino, valor.strip(), descriptiva=False)
                    elif accion == "Variante descriptiva":
                        nuevo = agregar_variante(base, termino, valor.strip(), descriptiva=True)
                    elif accion == "Habilidad nueva":
                        nuevo = agregar_termino(base, valor.strip(), categoria)
                    else:
                        nuevo = agregar_categoria(base, valor, rama)
                    ruta = guardar_version(nuevo, DIR_VOCABULARIO)
                    _aviso(f"Guardado en {ruta.name}. Reprocesa el aviso para aplicarlo.")
                except ValueError as error:
                    _aviso(str(error), "error")
                st.rerun()


# --- Pestañas -------------------------------------------------------------------------------

pipeline, ofertas, descartes, candidatos = st.tabs(
    ["▶️ Pipeline", "📄 Ofertas", "🗑️ Descartes", "🧩 Candidatos"]
)

with pipeline:

    @st.fragment(run_every="5s")
    def estado_corrida() -> None:
        en_curso = corrida_en_curso(bd)
        if en_curso is None:
            st.success("No hay ninguna corrida en curso.")
            return
        portales = ", ".join(en_curso.get("portales") or ["todo el crudo"])
        st.warning(
            f"**{en_curso['modo'].capitalize()} en curso** · {portales} · "
            f"desde {datos.hora_lima(en_curso['inicio'])} · pid {en_curso.get('pid')}"
        )
        nuevos = bd.trazas.count_documents({"fecha": {"$gte": en_curso["inicio"]}})
        publicados = bd.trazas.count_documents(
            {"fecha": {"$gte": en_curso["inicio"]}, "destino": "publicado"}
        )
        c1, c2 = st.columns(2)
        c1.metric("Avisos procesados en esta corrida", nuevos)
        c2.metric("Publicados", publicados)
        st.code(
            datos.ultimas_lineas(en_curso.get("archivo_registro")) or "(sin registro todavía)",
            language="log",
        )
        if st.button("⏹️ Detener corrida", key="detener"):
            try:
                os.killpg(os.getpgid(en_curso["pid"]), signal.SIGTERM)
                _aviso("Se envió la señal de detención.", "info")
            except (ProcessLookupError, PermissionError, KeyError, TypeError):
                _aviso("No se pudo detener: la corrida no la inició este panel.", "error")
            st.rerun()

    st.header("Corridas")
    estado_corrida()

    ocupado = corrida_en_curso(bd) is not None
    with st.form("nueva-corrida"):
        st.markdown(
            "**Nueva corrida** (respeta `robots.txt`, 2 s entre solicitudes y los cortes por rechazo)"
        )
        eleccion = st.radio("Portal", ["Bumeran", "Computrabajo", "Ambos"], horizontal=True)
        limite = st.number_input(
            "Límite de avisos nuevos por portal (0 = sin límite)", min_value=0, value=0, step=10
        )
        if st.form_submit_button("▶️ Iniciar corrida", disabled=ocupado, type="primary"):
            argumentos = ["campana", "--portal", eleccion.lower()]
            if limite:
                argumentos += ["--limite", str(int(limite))]
            pid = datos.lanzar(argumentos)
            _aviso(
                f"Corrida iniciada (pid {pid}). Computrabajo completo tarda ~30 min por las esperas.",
                "info",
            )
            st.rerun()
    if st.button(
        "🔁 Reprocesar todo el crudo",
        disabled=ocupado,
        help="Aplica el vocabulario vigente sin usar la red",
    ):
        pid = datos.lanzar(["reproceso"])
        _aviso(f"Reproceso iniciado (pid {pid}).", "info")
        st.rerun()

    st.subheader("Historial")
    historial = []
    for e in bd.ejecuciones.find().sort("inicio", -1).limit(30):
        r = e.get("resultados", {})
        historial.append(
            {
                "inicio (Lima)": datos.hora_lima(e["inicio"]),
                "modo": e["modo"],
                "embeddings": "sí"
                if e.get("parametros", {}).get("extraccion", {}).get("usar_via_semantica", True)
                else "no",
                "portales": ", ".join(e.get("portales") or []),
                "límite": e.get("limite") or "",
                "estado": e["estado"],
                "duración (s)": e.get("duracion_s"),
                "nuevos": sum(f.get("nuevos", 0) for f in e.get("fuentes", {}).values()),
                "publicados": r.get("publicados"),
                "descartes": sum((r.get("descartes") or {}).values()),
                "candidatos": r.get("candidatos_encolados"),
                "motivos": "; ".join(e.get("motivos") or []),
            }
        )
    st.dataframe(historial, hide_index=True, use_container_width=True)

with ofertas:
    st.header("Ofertas, una por una")
    c1, c2, c3 = st.columns([1, 1, 2])
    portal = c1.selectbox("Portal", ["Todos", *PORTALES], key="of-portal")
    destino = c2.selectbox("Destino", ["Todos", "publicado", "descartado"], key="of-destino")
    texto = c3.text_input("Buscar en el título", key="of-texto")
    filas = datos.avisos(
        bd,
        None if portal == "Todos" else portal,
        None if destino == "Todos" else destino,
        texto=texto,
    )
    st.caption(f"{len(filas)} avisos · selecciona una fila para ver su recorrido")
    elegida = seleccion(filas, "tabla-ofertas")
    if elegida:
        st.divider()
        detalle, lateral = st.columns([3, 2], gap="large")
        with detalle:
            d = mostrar_detalle(elegida["portal"], elegida["id_aviso"])
        with lateral:
            acciones(d, elegida["portal"], elegida["id_aviso"], "of")

with descartes:
    st.header("Gestión de descartes")
    conteo = {
        m: bd.ofertas_descartadas.count_documents({"motivo": m}) for m in datos.ETIQUETA_MOTIVO
    }
    for col, (motivo, n) in zip(st.columns(4), conteo.items(), strict=True):
        col.metric(datos.ETIQUETA_MOTIVO[motivo], n)
    c1, c2, c3 = st.columns([2, 1, 2])
    motivos = c1.multiselect(
        "Motivo",
        list(datos.ETIQUETA_MOTIVO),
        format_func=datos.ETIQUETA_MOTIVO.get,
        key="de-motivo",
    )
    portal = c2.selectbox("Portal", ["Todos", *PORTALES], key="de-portal")
    texto = c3.text_input("Buscar en el título", key="de-texto")
    filas = datos.avisos(
        bd, None if portal == "Todos" else portal, "descartado", motivos or None, texto
    )
    salida = io.StringIO()
    if filas:
        escritor = csv.DictWriter(salida, fieldnames=list(filas[0]))
        escritor.writeheader()
        escritor.writerows(filas)
    st.download_button(
        "⬇️ Exportar CSV",
        salida.getvalue().encode("utf-8-sig"),
        "descartes.csv",
        "text/csv",
        disabled=not filas,
    )
    elegida = seleccion(filas, "tabla-descartes")
    if elegida:
        st.divider()
        detalle, lateral = st.columns([3, 2], gap="large")
        with detalle:
            d = mostrar_detalle(elegida["portal"], elegida["id_aviso"])
        with lateral:
            acciones(d, elegida["portal"], elegida["id_aviso"], "de")

with candidatos:
    st.header("Cola de candidatos")
    st.caption(
        "Tramos que la vía semántica no pudo asignar con seguridad. Aprobar crea una versión nueva "
        "del vocabulario; después hay que reprocesar para aplicarla."
    )
    texto = st.text_input("Buscar tramo", key="ca-texto")
    filtro: dict[str, Any] = {"estado": "pendiente"}
    if texto:
        filtro["tramo"] = {"$regex": datos._escapar_regex(texto), "$options": "i"}
    pendientes = list(bd.candidatos_competencia.find(filtro).sort("puntaje", -1).limit(500))
    filas = [
        {
            "tramo": c["tramo"],
            "término cercano": c["termino_cercano"],
            "puntaje": c["puntaje"],
            "portal": c["portal"],
            "id_aviso": c["id_aviso"],
            "unidad": c["unidad"],
        }
        for c in pendientes
    ]
    st.caption(f"{len(filas)} pendientes")
    elegida = seleccion(filas, "tabla-candidatos")
    if elegida:
        c = pendientes[filas.index(elegida)]
        st.divider()
        st.markdown(f"**«{c['tramo']}»** en: _{c['unidad']}_  ({c['portal']} `{c['id_aviso']}`)")
        vocab = _vocab()
        nombres = sorted(t["nombre"] for t in vocab.terminos)
        modo = st.radio(
            "Aprobar como",
            ["Variante de un término existente", "Habilidad nueva"],
            horizontal=True,
            key=f"ca-modo-{c['_id']}",
        )
        with st.form(f"candidato-{c['_id']}"):
            if modo == "Variante de un término existente":
                termino = st.selectbox(
                    "Término",
                    nombres,
                    index=nombres.index(c["termino_cercano"])
                    if c["termino_cercano"] in nombres
                    else 0,
                )
                descriptiva = st.checkbox("Es una descripción, no una forma literal")
            else:
                nuevo = st.text_input("Nombre del término", value=c["tramo"])
                categoria = st.selectbox("Categoría", sorted(vocab.datos["categorias"]))
            b1, b2 = st.columns(2)
            aprobado = b1.form_submit_button("✅ Aprobar", type="primary")
            rechazado = b2.form_submit_button("❌ Rechazar")
        if aprobado:
            try:
                if modo == "Variante de un término existente":
                    ruta = aprobar(
                        bd, c["_id"], DIR_VOCABULARIO, termino=termino, descriptiva=descriptiva
                    )
                else:
                    ruta = aprobar(
                        bd,
                        c["_id"],
                        DIR_VOCABULARIO,
                        nuevo_termino=nuevo.strip(),
                        categoria=categoria,
                    )
                _aviso(f"Aprobado: {ruta.name}. Reprocesa para aplicarlo.")
            except ValueError as error:
                _aviso(str(error), "error")
            st.rerun()
        if rechazado:
            rechazar(bd, c["_id"])
            _aviso("Candidato rechazado.")
            st.rerun()
