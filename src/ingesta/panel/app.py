"""Panel de gestión del mecanismo de ingesta (R 2.3) y de la base de conocimiento (R 2.4).

docker compose up -d        →  http://localhost:8501
"""

import os
import signal
from collections.abc import Callable
from functools import partial
from typing import Any

import streamlit as st

from ingesta.campana import PORTALES
from ingesta.candidatos import DECISIONES, aprobar, importar_decisiones, rechazar
from ingesta.config import DIR_VOCABULARIO, RUTA_PARAMETROS, Entorno, cargar_parametros
from ingesta.conocimiento.busqueda import Filtros, buscar
from ingesta.conocimiento.textos import VECTORES
from ingesta.embeddings import ClienteTEI
from ingesta.gestion import (
    corrida_en_curso,
    publicar_manual,
    quitar_decision_manual,
    reprocesar_aviso,
)
from ingesta.panel import datos
from ingesta.servicios import conectar_bd, conectar_qdrant, construir_dependencias
from ingesta.vocabulario import (
    RAMAS,
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


@st.cache_resource
def _qdrant():
    return conectar_qdrant()


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
                            "origen": c.get("origen", "embedding"),
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


def exportar(
    todas: Callable[[], list[dict]],
    nombre: str,
    listas: dict[str, list[str]] | None = None,
    hay_filas: bool = True,
) -> None:
    """Descarga en CSV o Excel todas las filas que cumplen los filtros, sin el tope de la tabla.
    El archivo se arma recién al pulsar el botón (en otro hilo), así no frena cada recarga."""
    c1, c2, _ = st.columns([1, 1, 4])
    c1.download_button(
        "⬇️ CSV",
        lambda: datos.a_csv(todas()),
        f"{nombre}.csv",
        "text/csv",
        disabled=not hay_filas,
        key=f"csv-{nombre}",
    )
    c2.download_button(
        "⬇️ Excel",
        lambda: datos.a_xlsx(todas(), nombre[:31], listas),
        f"{nombre}.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        disabled=not hay_filas,
        key=f"xlsx-{nombre}",
    )


def importar_archivo() -> None:
    """Sube el CSV o Excel exportado con la columna `decision` completa: valida y luego aplica."""
    with st.expander("📥 Importar decisiones (CSV o Excel)"):
        st.caption(
            "Exporta la cola, completa `decision` (variante, nueva o rechazar; vacía = sigue "
            "pendiente) y, según el caso, `termino` y `descriptiva` o `nuevo_termino` y "
            "`categoria`. Todas las aprobaciones crean una sola versión del vocabulario."
        )
        ronda = st.session_state.setdefault("ca-importacion", 0)
        archivo = st.file_uploader(
            "Archivo de decisiones", type=["csv", "xlsx"], key=f"ca-archivo-{ronda}"
        )
        if archivo is None:
            return
        try:
            filas = datos.leer_tabla(archivo.name, archivo.getvalue())
        except Exception as error:  # archivo corrupto o con otro formato
            st.error(f"No se pudo leer el archivo: {error}")
            return
        plan = importar_decisiones(bd, filas, DIR_VOCABULARIO, aplicar=False)
        if not plan.filas:
            st.info("El archivo no tiene filas con `decision`.")
            return
        icono = {"ok": "✅", "error": "❌", "omitida": "⏭️"}
        resumen = [
            {
                "fila": f.fila,
                "estado": icono[f.estado],
                "tramo": f.tramo,
                "decision": f.decision,
                "detalle": f.detalle,
            }
            for f in plan.filas
        ]
        st.caption(
            f"✅ {plan.cuantas('ok')} válidas · ❌ {plan.cuantas('error')} con error · "
            f"⏭️ {plan.cuantas('omitida')} ya revisadas"
        )
        st.dataframe(resumen, hide_index=True, use_container_width=True)
        errores = [fila for fila in resumen if fila["estado"] == "❌"]
        c1, c2, _ = st.columns([2, 2, 3])
        c2.download_button(
            "⬇️ Filas con error",
            datos.a_csv(errores),
            "decisiones_con_error.csv",
            "text/csv",
            disabled=not errores,
        )
        if c1.button(
            f"Aplicar {plan.cuantas('ok')} decisiones",
            type="primary",
            disabled=not plan.cuantas("ok"),
        ):
            hecho = importar_decisiones(bd, filas, DIR_VOCABULARIO, aplicar=True)
            st.session_state["ca-importacion"] = ronda + 1
            _aviso(
                f"{hecho.cuantas('ok')} decisiones aplicadas."
                + (
                    f" Vocabulario nuevo: {hecho.version.name}. Reprocesa para aplicarlo."
                    if hecho.version
                    else ""
                )
            )
            st.rerun()


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

pipeline, ofertas, descartes, candidatos, conocimiento = st.tabs(
    ["▶️ Pipeline", "📄 Ofertas", "🗑️ Descartes", "🧩 Candidatos", "🧠 Base de conocimiento"]
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
    filtros = (None if portal == "Todos" else portal, None if destino == "Todos" else destino)
    filas = datos.avisos(bd, *filtros, texto=texto)
    st.caption(f"{len(filas)} avisos · selecciona una fila para ver su recorrido")
    exportar(
        lambda: datos.avisos(bd, *filtros, texto=texto, limite=0), "ofertas", hay_filas=bool(filas)
    )
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
    filtros = (None if portal == "Todos" else portal, "descartado", motivos or None, texto)
    filas = datos.avisos(bd, *filtros)
    exportar(lambda: datos.avisos(bd, *filtros, limite=0), "descartes", hay_filas=bool(filas))
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
        "Aprobar crea una versión nueva del vocabulario; después hay que reprocesar para aplicarla."
    )
    origen = st.radio(
        "Origen",
        ["Por embeddings", "Por descarte (léxicos)"],
        horizontal=True,
        key="ca-origen",
        help="Por embeddings: tramos que la vía semántica no pudo asignar con seguridad. "
        "Por descarte: palabras que no están en el vocabulario, ni son del español, ni comunes "
        "en inglés (p. ej. «Lambda»). Los léxicos se revisan por tramo: aprobar o rechazar "
        "resuelve todos sus avisos, y un rechazo vale también para los avisos futuros.",
    )
    lexicos = origen != "Por embeddings"
    texto = st.text_input("Buscar tramo", key="ca-texto")
    if lexicos:
        minimo = st.number_input(
            "Mínimo de avisos que lo mencionan",
            min_value=1,
            value=cargar_parametros().extraccion.via_lexica.min_avisos,
            key="ca-min-avisos",
        )
        pendientes = datos.candidatos_lexicos(bd, int(minimo), texto)
        filas = [
            {
                "tramo": c["tramo"],
                "avisos": c["n_avisos"],
                "ejemplo": c["unidad"],
                "portal": c["portal"],
                "id_aviso": c["id_aviso"],
            }
            for c in pendientes
        ]
        total = datos.total_candidatos(bd, True, int(minimo), texto)
        st.caption(f"{total} tramos pendientes · la tabla muestra {len(filas)}")
    else:
        pendientes = datos.candidatos_embedding(bd, texto)
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
        total = datos.total_candidatos(bd, False, texto=texto)
        st.caption(f"{total} pendientes · la tabla muestra {len(filas)}")
    vocab = _vocab()
    if lexicos:
        consulta = partial(datos.candidatos_lexicos, bd, int(minimo), texto, limite=0)
    else:
        consulta = partial(datos.candidatos_embedding, bd, texto, limite=0)
    st.caption(f"La exportación incluye los {total}.")
    exportar(
        lambda: datos.filas_para_decidir(consulta(), lexicos),
        "candidatos_lexicos" if lexicos else "candidatos_embeddings",
        {
            "decision": list(DECISIONES),
            "termino": sorted(t["nombre"] for t in vocab.terminos),
            "descriptiva": ["no", "si"],
            "categoria": sorted(set(vocab.datos["categorias"]) | set(RAMAS)),
        },
        hay_filas=bool(filas),
    )
    importar_archivo()
    elegida = seleccion(filas, "tabla-candidatos-lexicos" if lexicos else "tabla-candidatos")
    if elegida:
        c = pendientes[filas.index(elegida)]
        st.divider()
        st.markdown(f"**«{c['tramo']}»** en: _{c['unidad']}_  ({c['portal']} `{c['id_aviso']}`)")
        vocab = _vocab()
        nombres = sorted(t["nombre"] for t in vocab.terminos)
        if lexicos:
            st.caption(f"Mencionado en {c['n_avisos']} avisos.")
        modo = st.radio(
            "Aprobar como",
            ["Variante de un término existente", "Habilidad nueva"],
            index=1 if lexicos else 0,
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
            _aviso(
                "Tramo rechazado en todos los avisos; no volverá a encolarse."
                if lexicos
                else "Candidato rechazado."
            )
            st.rerun()

with conocimiento:
    st.header("Base de conocimiento (R 2.4)")
    p_bc = cargar_parametros().base_conocimiento
    estado = datos.estado_base(bd, _qdrant(), p_bc.coleccion)
    ultima = estado["ultima"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Ofertas en MongoDB", estado["ofertas"])
    c2.metric("Puntos en Qdrant", "—" if estado["puntos"] is None else estado["puntos"])
    c3.metric("Última sincronización", datos.hora_lima(ultima["inicio"]) if ultima else "nunca")
    if estado["error"]:
        st.error(f"Qdrant no disponible: {estado['error']}")
    elif estado["puntos"] != estado["ofertas"]:
        st.warning("Qdrant no coincide con MongoDB: sincroniza la base.")
    if ultima and ultima.get("resultados"):
        r = ultima["resultados"]
        st.caption(
            f"Última corrida ({ultima['estado']}): {r.get('creadas', 0)} creadas, "
            f"{r.get('actualizadas', 0)} actualizadas, {r.get('borradas', 0)} borradas · "
            f"{r.get('fragmentos', 0)} fragmentos · {ultima.get('duracion_s')} s"
        )
    if st.button(
        "🔄 Sincronizar",
        disabled=corrida_en_curso(bd) is not None,
        help="También corre sola al final de cada campaña y reproceso",
    ):
        pid = datos.lanzar(["vectorizar"])
        _aviso(
            f"Sincronización iniciada (pid {pid}). Sigue su registro en la pestaña Pipeline.",
            "info",
        )
        st.rerun()

    st.subheader("Probar búsqueda")
    st.caption("Sin LLM: muestra qué ofertas recuperaría el asistente y qué competencias piden.")
    with st.form("probar-busqueda"):
        consulta = st.text_input(
            "Pregunta del estudiante", placeholder="Sé Python y SQL, ¿a qué puedo postular?"
        )
        via = st.radio("Vectores", ["Los tres (RRF)", *VECTORES], horizontal=True)
        exigidas = st.multiselect(
            "Exigir competencias (filtro exacto en MongoDB)",
            sorted(t["nombre"] for t in _vocab().terminos),
        )
        enviado = st.form_submit_button("🔎 Buscar", type="primary")
    if enviado and consulta.strip():
        try:
            resultado = buscar(
                bd,
                _qdrant(),
                _tei(),
                p_bc,
                consulta,
                Filtros(competencias=tuple(exigidas)),
                None if via not in VECTORES else via,
            )
        except Exception as error:
            st.error(f"No se pudo buscar: {error}")
        else:
            filtradas = (
                "" if resultado.filtradas is None else f" · {resultado.filtradas} tras los filtros"
            )
            st.caption(f"{len(resultado.ofertas)} ofertas · vía {resultado.via}{filtradas}")
            if not resultado.suficiente:
                st.warning(f"Poca evidencia: menos de {p_bc.minimo_ofertas} ofertas.")
            col_ofertas, col_conteo = st.columns([3, 1])
            col_ofertas.dataframe(
                [
                    {
                        "puntaje": round(o.puntaje, 4),
                        "título": o.titulo,
                        "empresa": o.empresa,
                        "portal": o.portal,
                        "fragmento": o.fragmento,
                    }
                    for o in resultado.ofertas
                ],
                hide_index=True,
                use_container_width=True,
            )
            col_conteo.dataframe(
                [{"competencia": n, "ofertas": k} for n, k in resultado.conteo],
                hide_index=True,
                use_container_width=True,
            )
