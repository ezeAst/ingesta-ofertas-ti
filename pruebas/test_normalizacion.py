"""CP-16: descripción en texto plano y unidades que no cruzan secciones de Bumeran."""

from ingesta.normalizacion import SECCION_EXCLUIDA, SECCIONES_BUMERAN, html_a_texto, segmentar

# Así llega `detalle` desde la interfaz de Bumeran: sin etiquetas ni saltos de línea;
# las viñetas quedan separadas por doble espacio y los títulos de sección pegados.
DETALLE_BUMERAN = (
    "Buscamos un ingeniero de datos.¿Qué harás?Diseñar pipelines en PySpark.  "
    "Orquestar ETL con Airflow.  Gestionar Databricks sobre AWS (Jobs, Unity Catalog)"
    "Conocimientos y Certificaciones Indispensables: Databricks sobre AWS  PySpark en EMR/Glue  SQL"
    "Conocimientos y Certificaciones Deseables: Data Engineer Associate AWS"
    "Habilidades Blandas: Trabajo con equipos multidisciplinarios  Pensamiento analítico"
)


def test_html_a_texto_quita_etiquetas_y_entidades():
    texto = html_a_texto("<p>Hola&nbsp;mundo</p><br>Python &amp; SQL<ul><li>Git</li></ul>")
    assert "<" not in texto
    assert "&" in texto and "&amp;" not in texto
    assert texto.splitlines() == ["Hola mundo", "Python & SQL", "Git"]


def test_segmentar_bumeran_separa_vinetas_y_frases_pegadas():
    textos = [u.texto for u in segmentar(DETALLE_BUMERAN, "Bumeran")]
    assert "Diseñar pipelines en PySpark." in textos
    assert "Orquestar ETL con Airflow." in textos
    assert "PySpark en EMR/Glue" in textos  # «PySpark» no se parte en «Py» + «Spark»
    assert "¿Qué harás?" in textos


def test_segmentar_bumeran_asigna_secciones_sin_cruzarlas():
    unidades = segmentar(DETALLE_BUMERAN, "Bumeran")
    por_seccion = {}
    for u in unidades:
        por_seccion.setdefault(u.seccion, []).append(u.texto)
        assert not any(s in u.texto for s in SECCIONES_BUMERAN)  # el título no es una unidad
    indisp = "Conocimientos y Certificaciones Indispensables"
    assert por_seccion[indisp] == ["Databricks sobre AWS", "PySpark en EMR/Glue", "SQL"]
    assert por_seccion["Habilidades Blandas"] == [
        "Trabajo con equipos multidisciplinarios",
        "Pensamiento analítico",
    ]
    assert "Gestionar Databricks sobre AWS (Jobs, Unity Catalog)" in por_seccion[None]


def test_segmentar_bumeran_separa_titulos_en_mayusculas_pegados_a_la_frase_anterior():
    detalle = (
        "Experiencia como Analista SOC (L1/L2) o en análisis de logs."
        "CONOCIMIENTOS TÉCNICOS Dominio de plataformas SIEM.  "
        "Habilidad avanzada con Wireshark.COMPETENCIAS Capacidad analítica."
    )
    assert [u.texto for u in segmentar(detalle, "Bumeran")] == [
        "Experiencia como Analista SOC (L1/L2) o en análisis de logs.",
        "CONOCIMIENTOS TÉCNICOS Dominio de plataformas SIEM.",
        "Habilidad avanzada con Wireshark.",
        "COMPETENCIAS Capacidad analítica.",
    ]


def test_segmentar_bumeran_no_parte_nombres_con_punto():
    # Guarda contra el exceso de cortes: «Node.js», «ASP.NET» y «Vue.JS» no son títulos pegados.
    detalle = "Stack: Node.js, ASP.NET y Vue.JS con Next.js."
    assert [u.texto for u in segmentar(detalle, "Bumeran")] == [detalle]


def test_segmentar_computrabajo_usa_saltos_y_vinetas():
    texto = (
        "Requisitos:\n- Python avanzado\n• Docker básico\nOfrecemos: planilla. Línea de carrera."
    )
    textos = [u.texto for u in segmentar(texto, "Computrabajo")]
    assert textos == [
        "Requisitos:",
        "Python avanzado",
        "Docker básico",
        "Ofrecemos: planilla.",
        "Línea de carrera.",
    ]
    secciones = [u.seccion for u in segmentar(texto, "Computrabajo")]
    assert secciones == [None, None, None, SECCION_EXCLUIDA, SECCION_EXCLUIDA]


def test_quitar_emojis_los_reemplaza_por_un_espacio():
    from ingesta.normalizacion import quitar_emojis

    limpio = quitar_emojis("✅Python 🚀 y SQL👍🏽, 👨‍💻 Git ☁️ AWS 🇵🇪")
    assert limpio.split() == ["Python", "y", "SQL", ",", "Git", "AWS"]
    assert quitar_emojis("C# y .NET — 100% remoto © 2026") == "C# y .NET — 100% remoto © 2026"


def _secciones(texto, portal="Computrabajo"):
    return {u.texto: u.seccion for u in segmentar(texto, portal)}


def test_titulo_suelto_de_beneficios_excluye_las_unidades_siguientes():
    s = _secciones(
        "Requisitos:\n- Python avanzado\n¿Qué ofrecemos?\nEPS al 100%.\nBono de alimentación."
    )
    assert s["Python avanzado"] is None
    assert s["¿Qué ofrecemos?"] == SECCION_EXCLUIDA
    assert s["EPS al 100%."] == SECCION_EXCLUIDA
    assert s["Bono de alimentación."] == SECCION_EXCLUIDA


def test_titulo_en_linea_de_beneficios_excluye_la_unidad_y_las_siguientes():
    s = _secciones("Beneficios: Capacitación permanente.\nDescuentos corporativos.")
    assert set(s.values()) == {SECCION_EXCLUIDA}


def test_la_zona_excluida_termina_en_un_titulo_de_requisitos():
    s = _secciones("¿Qué ofrecemos?\nPlanilla completa.\nRequisitos:\nDocker básico")
    assert s["Planilla completa."] == SECCION_EXCLUIDA
    assert s["Requisitos:"] is None
    assert s["Docker básico"] is None


def test_una_etiqueta_dentro_de_beneficios_no_cierra_la_zona():
    # Aviso 1118456720: «Oportunidad internacional:» es un beneficio más, no un título nuevo.
    s = _secciones(
        "¿QUÉ OFRECEMOS?\nOportunidad internacional: viajes a España.\nCapacitación continua."
    )
    assert set(s.values()) == {SECCION_EXCLUIDA}


def test_presentacion_de_la_empresa_se_excluye_hasta_las_funciones():
    # Aviso 1118398064: «¿Por qué ser parte de…?» presenta a la empresa; las funciones vuelven.
    s = _secciones(
        "¿Por qué ser parte de SONDA?\nAmamos lo que hacemos.\n"
        "En esta función tendrás que: Atender incidentes de soporte."
    )
    assert s["Amamos lo que hacemos."] == SECCION_EXCLUIDA
    assert s["En esta función tendrás que: Atender incidentes de soporte."] is None


def test_condiciones_y_horario_del_puesto_se_excluyen():
    s = _secciones("DETALLES DEL PUESTO: Lugar de trabajo San Isidro.\nHorario: Lunes a Viernes.")
    assert set(s.values()) == {SECCION_EXCLUIDA}


def test_una_seccion_de_bumeran_cierra_la_zona_excluida():
    detalle = (
        "¿Qué ofrecemos?EPS al 100%.Habilidades Blandas: Trabajo con equipos multidisciplinarios"
    )
    s = _secciones(detalle, "Bumeran")
    assert s["EPS al 100%."] == SECCION_EXCLUIDA
    assert s["Trabajo con equipos multidisciplinarios"] == "Habilidades Blandas"
