# R 2.4 Base de conocimiento: plan de implementación

> **Para agentes:** sub-skill requerida: superpowers:executing-plans (ejecución en esta sesión, elegida por el usuario). Los pasos usan casillas (`- [ ]`).

**Objetivo:** cargar `ofertas_laborales` en Qdrant con tres vectores por oferta, mantenerla sincronizada tras cada campaña y ofrecer `buscar()` para el asistente (R 3).

**Arquitectura:** paquete nuevo `ingesta.conocimiento` dentro del repo de ingesta, con cuatro piezas: textos por vector, colección de Qdrant, sincronización (se registra en `ejecuciones`) y búsqueda (MongoDB filtra, Qdrant ordena con RRF y MongoDB entrega los datos). Se engancha al final de `ejecutar_campana` y `ejecutar_reproceso` sin que un fallo de Qdrant tumbe la campaña.

**Tecnología:** Python 3.13, `qdrant-client` 1.19 (ya instalado), Qdrant 1.19.1, TEI con `multilingual-e5-large`, pymongo, typer y Streamlit.

**Spec:** `../resultados/apoyo R 2.4/R 2.4 - Decisiones de diseno.md` (V1–V18), desde la raíz de `tesis_2`.

**Fuera de este plan:** calibración de umbrales con ~15 preguntas (V14), comparación de modelos (V15), comparación con y sin `fragmentos` (V5), entregable docx y sección 5.2.4. Necesitan el conjunto de preguntas y van en un plan posterior. Aquí los umbrales quedan en 0,0 (sin corte) y PROVISIONALES.

## Restricciones globales

- Solo se vectoriza `ofertas_laborales`; MongoDB es la fuente de verdad (V1, V6).
- Vectores nombrados: `titulo`, `competencias`, `fragmentos` (multivector, `max_sim`), todos con distancia coseno (V2, V3).
- Prefijos E5: `passage: ` para las ofertas y `query: ` para las consultas (I15).
- Fragmento: `passage: <título> — <fragmento>`, hasta 400 tokens, sin la sección «Beneficios y empresa» (V3).
- Id del punto: UUID5 de `"<portal>:<id_aviso>"`. Huella: SHA-256 de título + descripción + nombres de competencias (V10).
- Payload de Qdrant: solo `portal`, `id_aviso`, `huella` y `fragmentos` (textos) (V6).
- Filtros exactos en MongoDB; Qdrant solo ordena dentro de esos ids (`has_id`) (V7).
- Búsqueda por defecto: tres *prefetch* fusionados con RRF; `via` fuerza uno. El umbral va dentro de cada *prefetch* y `limite` sobre el resultado (V18).
- Parámetros en `config/parametros.toml`, sección `[base_conocimiento]`: `limite = 50`, `minimo_ofertas = 10` y umbrales por vector (V13).
- Un fallo de Qdrant no cambia el estado de la campaña: queda `base_conocimiento.estado = "desactualizada"` (V11).
- Nada de texto crudo en reportes ni registros (compromiso 7).
- Los casos del plan de pruebas se numeran `BC-NN` y se citan en el docstring del módulo de prueba, como `CP-NN` en R 2.3.
- Estilo del repo: código y nombres en español, ruff limpio (línea de 100), `pytest -m integracion` para lo que usa MongoDB, TEI o Qdrant.

## Puntos a vigilar en la revisión

1. **Oferta sin fragmentos:** si toda la descripción cae en «Beneficios y empresa» o queda vacía, el multivector necesita al menos un vector. Se usa el título como único fragmento. Lo prueba la Tarea 2.
2. **Unidad que pasa de 400 tokens:** una sola frase larga va sola en su fragmento. Si pasa de 512, TEI la recorta y se cuenta en `fragmentos_recortados` sin fallar. Lo prueba la Tarea 2.
3. **Filtro que no deja ninguna oferta:** `buscar` devuelve un resultado vacío y no busca en toda la colección. Una lista vacía en `has_id` no puede llegar a Qdrant. Lo prueba la Tarea 5.
4. **respx intercepta a Qdrant:** `qdrant-client` usa httpx, así que las pruebas de campaña con `respx_mock` necesitan `pass_through` para el host de Qdrant o un doble que falle a propósito. Lo cubre la Tarea 4.
5. **Vectorizar durante una corrida:** `ingesta vectorizar` y el botón del panel se niegan si `corrida_en_curso(bd)` no es `None`, igual que `campana`. Lo prueba la Tarea 6.

---

### Tarea 1: configuración, conexión a Qdrant y conteo de tokens

**Archivos:**
- Modificar: `src/ingesta/config.py`, `config/parametros.toml`, `src/ingesta/embeddings.py`, `src/ingesta/servicios.py`, `compose.yaml` (quitar `profiles: ["r24"]` de `qdrant` para que `docker compose up -d` lo levante; no se añade a `depends_on`, ver V11), `pruebas/conftest.py`, `pruebas/utiles.py`
- Pruebas: `pruebas/test_config.py`, `pruebas/test_embeddings.py`

**Interfaces que produce:**
- `ParamsBaseConocimiento(coleccion: str, prefijo_pasaje: str, prefijo_consulta: str, max_tokens_fragmento: int, lote: int, limite: int, minimo_ofertas: int, umbral_relevancia: dict[str, float])`; `Parametros.base_conocimiento`.
- `Entorno.qdrant_url: str = "http://localhost:6333"`, `Entorno.qdrant_api_key: str | None = None`.
- `ClienteTEI.contar_tokens(textos: list[str]) -> list[int]`: `POST /tokenize` con `add_special_tokens: true`, por lotes de `self._lote`.
- `EmbebedorPalabras.contar_tokens(textos) -> list[int]`: número de palabras + 2.
- `servicios.conectar_qdrant() -> QdrantClient` (con `url` y `api_key` del entorno, `timeout=10`).
- Fixture `qdrant`: cliente real; borra la colección `ofertas_pruebas` antes y después. Fixture `params_bc`: `params_bow` con `base_conocimiento.coleccion = "ofertas_pruebas"`.

Valores de `[base_conocimiento]`: `coleccion = "ofertas"`, `prefijo_pasaje = "passage: "`, `prefijo_consulta = "query: "`, `max_tokens_fragmento = 400`, `lote = 32`, `limite = 50`, `minimo_ofertas = 10` y `[base_conocimiento.umbral_relevancia]` con `titulo`, `competencias` y `fragmentos` en `0.0`. Un comentario indica que son PROVISIONALES y se calibran con V14.

- [ ] Prueba `test_parametros_de_base_conocimiento`: `cargar_parametros().base_conocimiento` tiene `limite == 50`, `minimo_ofertas == 10`, `max_tokens_fragmento == 400` y las tres claves de umbral.
- [ ] Prueba `test_contar_tokens_por_lotes` (respx sobre `/tokenize`): 70 textos dan 70 conteos en orden y 3 solicitudes.
- [ ] Prueba de integración `test_contar_tokens_con_tei_real`: `contar_tokens(["passage: Python"])[0]` está entre 3 y 10.
- [ ] Ejecutar y ver que fallan; implementar; ejecutar `docker compose run --rm ingesta pytest pruebas/test_config.py pruebas/test_embeddings.py` en verde.
- [ ] `docker compose up -d` y comprobar que `qdrant` queda levantado sin perfil.
- [ ] Commit: `R 2.4: parámetros, conexión a Qdrant y conteo de tokens`.

### Tarea 2: textos de cada vector

**Archivos:**
- Crear: `src/ingesta/conocimiento/__init__.py`, `src/ingesta/conocimiento/textos.py`
- Pruebas: `pruebas/test_conocimiento_textos.py` (BC-01 a BC-04)

**Interfaces que produce** (`oferta` es el documento de MongoDB):
- `VECTORES = ("titulo", "competencias", "fragmentos")`
- `id_punto(portal: str, id_aviso: str) -> str`: UUID5 con un `NAMESPACE` fijo del módulo.
- `huella(oferta: dict) -> str`: SHA-256 hex de `titulo`, `descripcion` y los `nombre` de `competencias` en orden, unidos por `\n`.
- `texto_titulo(oferta, prefijo: str) -> str` → `f"{prefijo}{titulo}"`.
- `texto_competencias(oferta, prefijo: str) -> str` → `f"{prefijo}{titulo}. Competencias: {', '.join(nombres únicos en orden)}"`.
- `fragmentar(oferta, prefijo: str, max_tokens: int, contar_tokens: Callable[[list[str]], list[int]]) -> list[str]`: devuelve los textos ya con el prefijo y el título.

Algoritmo de `fragmentar`:
1. `segmentar(descripcion, portal)` y se quitan las unidades de `SECCION_EXCLUIDA`.
2. Se recorren las unidades en orden y se acumulan en el fragmento actual. El fragmento se cierra si cambia `unidad.seccion` o si `contar_tokens` del texto completo (`f"{prefijo}{titulo} — {' '.join(acumuladas)}"`) pasaría de `max_tokens`.
3. Si se cerró por tamaño dentro de la misma sección, el siguiente fragmento empieza repitiendo la última unidad del anterior (solapamiento de una unidad).
4. Una unidad que sola pasa el límite queda como su propio fragmento.
5. Sin unidades, se devuelve `[f"{prefijo}{titulo}"]`.

Para no llamar a TEI por cada unidad, se cuentan los tokens de todas las unidades en una sola llamada y se suman, con un margen fijo para el prefijo y el título (que también se cuentan una vez).

- [ ] BC-01 `test_id_punto_es_estable_y_distingue_portal`: el mismo par da el mismo id; `("Bumeran","1")` y `("Computrabajo","1")` dan ids distintos; el resultado es un UUID válido.
- [ ] BC-02 `test_huella_cambia_si_cambian_las_competencias` y `test_huella_no_depende_de_otros_campos` (cambiar `fuente.fecha_extraccion` no la altera).
- [ ] BC-03 `test_texto_competencias`: con `titulo="Analista"` y competencias Python, SQL, Python sale `"passage: Analista. Competencias: Python, SQL"`.
- [ ] BC-04, con `EmbebedorPalabras().contar_tokens`:
  - `test_fragmentar_excluye_beneficios`: con una descripción «Requisitos: Python y SQL. ¿Qué ofrecemos? Bono de alimentación», ningún fragmento contiene «Bono».
  - `test_fragmentar_parte_por_tamano_con_solapamiento`: con 30 frases de 10 palabras en una sección y `max_tokens=60`, hay más de 1 fragmento, cada uno ≤ 60 tokens salvo los de una sola frase, y el fragmento i+1 empieza con la última frase del i.
  - `test_fragmentar_sin_unidades_devuelve_el_titulo`: con una descripción que solo tiene beneficios, sale `["passage: Analista"]`.
  - `test_unidad_larga_va_sola`: una frase de 100 palabras con `max_tokens=60` queda como un único fragmento.
- [ ] Ejecutar y ver que fallan; implementar; ejecutar en verde; ruff.
- [ ] Commit: `R 2.4: textos de los vectores titulo, competencias y fragmentos`.

### Tarea 3: colección de Qdrant y sincronización

**Archivos:**
- Crear: `src/ingesta/conocimiento/coleccion.py`, `src/ingesta/conocimiento/sincronizacion.py`
- Pruebas: `pruebas/test_conocimiento_sincronizacion.py` (BC-05 a BC-09, `integracion`)

**Interfaces que consume:** las de la Tarea 2, `ParamsBaseConocimiento`, y un embebedor con `vectorizar` y `contar_tokens`.

**Interfaces que produce:**
- `coleccion.asegurar(cliente: QdrantClient, nombre: str, dim: int) -> None`: si no existe, la crea con `titulo` y `competencias` como `VectorParams(size=dim, distance=COSINE)` y `fragmentos` igual más `multivector_config=MultiVectorConfig(comparator=MAX_SIM)`.
- `coleccion.huellas(cliente, nombre) -> dict[str, str]`: id → huella, con `scroll` paginado, `with_payload=["huella"]` y `with_vectors=False`.
- `sincronizacion.sincronizar(bd: Database, cliente: QdrantClient, embebedor, p: ParamsBaseConocimiento, todo: bool = False) -> dict[str, Any]`, que devuelve `{"creadas", "actualizadas", "borradas", "sin_cambios", "puntos", "fragmentos", "fragmentos_recortados", "por_portal": {portal: n}}`.

Flujo de `sincronizar`:
1. Si `todo`, borra la colección.
2. `asegurar` con `dim` = ancho de `embebedor.vectorizar([p.prefijo_pasaje + "x"])`.
3. Lee de MongoDB las ofertas con la proyección mínima y calcula id y huella.
4. Compara contra `huellas()`.
5. Para las nuevas y las cambiadas, en lotes de `p.lote` ofertas, arma los tres textos y hace **una** llamada a `vectorizar` por lote con todos los textos concatenados. Después hace `upsert` de `PointStruct(id, vector={"titulo": v, "competencias": v, "fragmentos": [v…]}, payload={portal, id_aviso, huella, fragmentos: textos sin prefijo})`.
6. Hace `delete` de los ids sobrantes.

`fragmentos_recortados` cuenta los fragmentos de más de 512 tokens. `puntos` es el conteo final de Qdrant (`count(exact=True)`).

- [ ] BC-05 `test_primera_carga_crea_un_punto_por_oferta`: publicar 3 ofertas con `ejecutar_campana(dep())` (como en `test_campana.simular_portales`) y luego `sincronizar(...)`. Resultado: `creadas == 3` y `puntos == 3`. El punto de una oferta tiene los tres vectores y `fragmentos` es una lista de al menos un vector.
- [ ] BC-06 `test_segunda_sincronizacion_sin_cambios_no_toca_nada`: `sin_cambios == 3` y `creadas == actualizadas == borradas == 0`. El embebedor espía no recibió textos `passage:` de ofertas.
- [ ] BC-07 `test_oferta_modificada_se_actualiza`: al cambiar las `competencias` de una oferta en MongoDB, `actualizadas == 1` y la huella del punto coincide con la nueva.
- [ ] BC-08 `test_oferta_borrada_sale_de_qdrant`: al borrar una oferta en MongoDB, `borradas == 1` y `puntos == 2`.
- [ ] BC-09 `test_todo_reconstruye_desde_cero`: `sincronizar(..., todo=True)` da `creadas == 3` aunque ya existiera la colección.
- [ ] Ejecutar y ver que fallan; implementar; ejecutar en verde; ruff.
- [ ] Commit: `R 2.4: colección de Qdrant y sincronización incremental`.

### Tarea 4: registro en `ejecuciones` y enganche con la campaña

**Archivos:**
- Modificar: `src/ingesta/campana.py`, `src/ingesta/servicios.py`
- Crear: `src/ingesta/conocimiento/vectorizacion.py`
- Pruebas: `pruebas/test_conocimiento_vectorizacion.py` (BC-10, BC-11, `integracion`)

**Interfaces:**
- `Dependencias.qdrant: QdrantClient | None = None`; `construir_dependencias` lo llena con `conectar_qdrant()`.
- `vectorizacion.ejecutar_vectorizacion(dep: Dependencias, todo: bool = False) -> dict[str, Any]`. Abre su propio documento en `ejecuciones` con `modo="vectorizacion"`, reutilizando `_abrir` y `_cerrar` de `campana` (hay que exponerlos sin guion bajo o moverlos a `registro.py`; se elige moverlos a `registro.py` como `abrir_ejecucion` y `cerrar_ejecucion`). Usa `bitacora(dep.dir_logs, "vectorizacion", inicio)` y guarda el resultado de `sincronizar` en `resultados` y `{"coleccion", "modelo"}` en el documento.
- En `ejecutar_campana` y `ejecutar_reproceso`, después de `_cerrar`: si `dep.qdrant` no es `None`, se intenta `ejecutar_vectorizacion(dep)` y se añade al documento de la campaña `base_conocimiento = {"estado": "actualizada", "ejecucion": <id>}`. Ante cualquier excepción se registra `{"estado": "desactualizada", "error": str(e)}` en el log. Con `dep.qdrant is None` queda `{"estado": "omitida"}`. El `estado` de la campaña no cambia.

`Acumulador.como_documento` no sirve para la vectorización: `cerrar_ejecucion` debe aceptar `resultados` como diccionario ya armado.

- [ ] BC-10 `test_vectorizacion_queda_en_ejecuciones`: tras `ejecutar_vectorizacion(dep)`, el documento tiene `modo == "vectorizacion"`, `estado == "exitosa"`, `resultados.creadas == 3` y `duracion_s` numérico.
- [ ] BC-11 `test_qdrant_caido_no_tumba_la_campana`: con `dep.qdrant` apuntando a `http://127.0.0.1:1`, la campaña termina con su estado normal y `base_conocimiento.estado == "desactualizada"`.
- [ ] `test_campana_actualiza_la_base`: con Qdrant real, `base_conocimiento.estado == "actualizada"`. Las pruebas de campaña que usan `respx_mock` necesitan `respx_mock.route(host="qdrant").pass_through()`.
- [ ] Toda la suite sigue en verde: `docker compose run --rm ingesta pytest`.
- [ ] Commit: `R 2.4: sincronización automática al final de campaña y reproceso`.

### Tarea 5: `buscar()`

**Archivos:**
- Crear: `src/ingesta/conocimiento/busqueda.py`
- Pruebas: `pruebas/test_conocimiento_busqueda.py` (BC-12 a BC-17, `integracion`)

**Interfaces que produce:**
- `Filtros` (dataclass frozen, todo opcional): `competencias: tuple[str, ...]`, `categorias`, `tipos`, `niveles`, `portales`, `desde: datetime | None`, `hasta: datetime | None`, más `vacio() -> bool`.
- Traducción a MongoDB:
  - `competencias` usa `$all` sobre `competencias.nombre`;
  - `categorias`, `tipos` y `portales` usan `$in`;
  - `niveles` usa `$elemMatch` sobre `{nivel_requerido: {$in}}`, más `nombre: {$in: competencias}` si hay competencias (V8: solo cuando se pide);
  - las fechas filtran sobre `fecha_publicacion`;
  - los campos se combinan con AND.
- `OfertaEncontrada(portal, id_aviso, titulo, empresa, url, fecha_publicacion, puntaje: float, fragmento: str, competencias: list[str])`.
- `ResultadoBusqueda(ofertas: list[OfertaEncontrada], conteo: list[tuple[str, int]], suficiente: bool, via: str, filtradas: int | None)`. `via` vale `"rrf"` o el nombre del vector; `filtradas` es el número de ofertas que dejó MongoDB, o `None` sin filtros.
- `buscar(bd, cliente, embebedor, p: ParamsBaseConocimiento, consulta: str, filtros: Filtros | None = None, via: str | None = None) -> ResultadoBusqueda`. Lanza `ValueError` si la consulta está vacía o si `via` no está en `VECTORES`.

Flujo:
1. Si hay filtros, MongoDB devuelve los pares (portal, id_aviso) y se convierten con `id_punto`. Una lista vacía devuelve `ResultadoBusqueda([], [], False, via, 0)` sin consultar Qdrant.
2. Se vectoriza `p.prefijo_consulta + consulta`.
3. Con `via`: `query_points(using=via, query=v, query_filter=HasId, limit=p.limite, score_threshold=p.umbral_relevancia[via], with_payload=True, with_vectors=["fragmentos"])`. Sin `via`: `query_points(prefetch=[Prefetch(query=v, using=n, filter=…, limit=p.limite, score_threshold=p.umbral_relevancia[n]) for n in VECTORES], query=FusionQuery(fusion=Fusion.RRF), limit=p.limite, …)`.
4. `fragmento` es el texto del payload cuyo vector da el mayor producto punto con `v`.
5. MongoDB entrega las ofertas en el orden de Qdrant.
6. `conteo` es un `Counter` de los nombres de competencias, ordenado de mayor a menor (y por nombre en los empates).
7. `suficiente = len(ofertas) >= p.minimo_ofertas`.

Las pruebas usan `EmbebedorPalabras` (similitud por palabras compartidas) y tres ofertas sintéticas pensadas para que cada vector gane en un caso: «Analista de Datos» (Python, SQL), «Desarrollador Backend» (Java, Docker) y «Especialista DevOps», cuya descripción habla de «automatizar despliegues».

- [ ] BC-12 `test_via_titulo`: `buscar(..., "analista de datos", via="titulo").ofertas[0].titulo == "Analista de Datos"`.
- [ ] BC-13 `test_via_competencias` («java docker» → Backend primero) y `test_via_fragmentos` («automatizar despliegues» → DevOps primero, con `fragmento` que contiene «automatizar despliegues»).
- [ ] BC-14 `test_rrf_por_defecto`: sin `via`, `resultado.via == "rrf"` y el primero es la oferta que encabeza dos de las tres listas. Se verifica también que `via` inválida lanza `ValueError`.
- [ ] BC-15 `test_filtros_restringen_en_mongodb`: `Filtros(competencias=("Java",))` deja solo Backend y `filtradas == 1`. Con `Filtros(competencias=("Cobol",))` sale una lista vacía, `filtradas == 0`, y un `cliente` espía muestra que no se llamó a `query_points`.
- [ ] BC-16 `test_conteo_y_suficiencia`: `conteo` suma las competencias de las ofertas devueltas; con `minimo_ofertas=10` y 3 ofertas, `suficiente is False`.
- [ ] BC-17 `test_umbral_por_vector_corta_dentro_del_prefetch`: con `umbral_relevancia={"titulo": 0.99, "competencias": 0.99, "fragmentos": 0.99}` y una consulta sin palabras en común, no sale ninguna oferta.
- [ ] Ejecutar y ver que fallan; implementar; ejecutar en verde; ruff.
- [ ] Commit: `R 2.4: búsqueda con filtros en MongoDB y fusión RRF en Qdrant`.

### Tarea 6: comandos `vectorizar` y `buscar`

**Archivos:**
- Modificar: `src/ingesta/cli.py` (la ayuda principal pasa a «R 2.3 / R 2.4»)
- Pruebas: `pruebas/test_cli.py` (BC-18)

**Interfaces:**
- `ingesta vectorizar [--todo]`: se niega con código 3 si `corrida_en_curso(bd)`. Imprime creadas, actualizadas, borradas, sin cambios, puntos, fragmentos y duración.
- `ingesta buscar CONSULTA [--via titulo|competencias|fragmentos] [--competencia X]... [--categoria X]... [--portal X]...`: imprime una línea por oferta (puntaje, portal, título, empresa), el top 15 del conteo de competencias y un aviso «poca evidencia» si `suficiente` es falso.

- [ ] BC-18 `test_la_ayuda_lista_vectorizar_y_buscar` (se amplía la tupla del test existente) y `test_vectorizar_se_niega_con_corrida_en_curso` (se inserta en `bd.ejecuciones` un documento `en_curso` con el pid del proceso de prueba).
- [ ] Ejecutar y ver que fallan; implementar; ejecutar en verde.
- [ ] Commit: `R 2.4: comandos vectorizar y buscar`.

### Tarea 7: pestaña «Base de conocimiento» del panel

**Archivos:**
- Modificar: `src/ingesta/panel/datos.py`, `src/ingesta/panel/app.py`
- Pruebas: `pruebas/test_panel_datos.py`, `pruebas/test_panel_app.py` (BC-19)

**Interfaces:**
- `datos.estado_base(bd, cliente, coleccion: str) -> dict`, que devuelve `{"ofertas": int, "puntos": int | None, "ultima": dict | None, "error": str | None}`. `ultima` es la última ejecución `modo="vectorizacion"`; si Qdrant no responde, `puntos` es `None` y se llena `error`.
- La pestaña quinta, «🧠 Base de conocimiento», tiene:
  - métricas de ofertas en MongoDB y puntos en Qdrant;
  - la fecha de la última sincronización;
  - el botón «Sincronizar» (`datos.lanzar(["vectorizar"])`, deshabilitado si hay una corrida);
  - un formulario «Probar búsqueda»: consulta, selector de vía (Todas/Título/Competencias/Fragmentos) y multiselect de competencias del vocabulario. Muestra una tabla de ofertas (puntaje, título, empresa, portal, fragmento) y otra de conteo de competencias.

- [ ] Prueba `test_estado_base_sin_qdrant`: con un cliente a `http://127.0.0.1:1`, `puntos is None` y `error` no vacío.
- [ ] BC-19: se amplía `test_cp46…` (o se crea `test_bc19_pestana_base_conocimiento`) para que la lista de pestañas incluya «🧠 Base de conocimiento» y la app corra sin excepción.
- [ ] Ejecutar y ver que fallan; implementar; ejecutar en verde.
- [ ] Commit: `R 2.4: pestaña Base de conocimiento en el panel`.

### Tarea 8: carga real, plan de pruebas y documentación

**Archivos:**
- Crear: `docs/plan_de_pruebas_base_conocimiento.md`, con el mismo formato que `plan_de_pruebas_funcionales.md`. Contiene los casos BC-01 a BC-19 en tres bloques (carga: BC-05 a BC-11; embeddings: BC-01 a BC-04 más la prueba de tokens real; recuperación: BC-12 a BC-17), las pruebas de interfaz (BC-18 y BC-19), el registro de ejecución y «Aprobación del tesista: pendiente».
- Modificar: `README.md` (Qdrant sin perfil, comandos nuevos), `resultados/apoyo R 2.4/R 2.4 - Decisiones de diseno.md` (anotar las decisiones de implementación de este plan que no estaban en V1–V18: umbral 0,0 provisional, solapamiento de una unidad, título como fragmento de respaldo y semántica de los filtros).

- [ ] Suite completa en verde y ruff limpio: `docker compose run --rm ingesta pytest` y `ruff check .`.
- [ ] Carga real: `docker compose run --rm ingesta ingesta vectorizar --todo`. Esperado: `puntos` igual al número de documentos de `ofertas_laborales` (2.529 al 2026-10-25). Anotar fragmentos, recortados y duración.
- [ ] Segunda corrida `ingesta vectorizar`: `sin_cambios` igual al total y duración de pocos segundos.
- [ ] Búsqueda de humo: `ingesta buscar "sé Python y SQL, ¿a qué puedo postular?"` devuelve 50 ofertas y Python y SQL quedan en el conteo.
- [ ] Llenar el registro de ejecución del plan de pruebas con el total de casos y el commit.
- [ ] Commit y push: `R 2.4: plan de pruebas de la base de conocimiento y carga inicial`.
