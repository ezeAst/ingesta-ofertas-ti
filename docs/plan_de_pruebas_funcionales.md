# Plan de pruebas funcionales del módulo de extracción (R 2.3)

**Resultado:** R 2.3, proceso de extracción y procesamiento de ofertas laborales no estructuradas para la obtención de datos organizados sobre requisitos y competencias.
**Medio de verificación (Tabla 2):** repositorio de código fuente del módulo de extracción, log de ejecución con dataset de muestra y plan de pruebas funcionales del módulo de extracción.
**Indicador:** 100 % de casos de prueba funcionales ejecutados y aprobados por el tesista.
**Autor:** Sebastián Antonio Martínez Toledo · **Fecha:** 27 de setiembre de 2026 · **Revisión:** 5 de octubre de 2026 · **Versión:** 1.1

La estructura sigue, en forma abreviada, la plantilla de plan de pruebas y de especificación de casos de ISO/IEC/IEEE 29119-3:2021.

## 1. Alcance

Se prueba el mecanismo diseñado en el Anexo J (R 2.2), desde la relectura de `robots.txt` hasta la escritura validada en MongoDB, con los ajustes registrados en «R 2.3 - Decisiones de implementacion.md» (I1 a I30) y las funciones añadidas durante la implementación: panel de gestión, trazas, vía léxica, publicación manual y decisiones en lote (sección 5.7). Quedan fuera los *embeddings* de la base vectorial y la recuperación semántica, que se prueban en R 2.4. También queda fuera la calidad de la extracción medida con precisión, exhaustividad y F1, que se trata aparte en la sección 7 porque no es un caso de aprobado o rechazado.

## 2. Referencias

| Documento | Uso en este plan |
|---|---|
| Anexo J, Documento de diseño del mecanismo de ingesta (R 2.2) | Componentes (§5), flujo (§6), colecciones (§7), conceptos transversales (§9), escenarios (§13) |
| R 2.3 - Decisiones de implementación | Decisiones I1 a I30 y parámetros por defecto |
| Anexo I, Documento de análisis de fuentes (R 2.1) | Protocolo de siete compromisos (C1 a C7) y riesgos R1 a R5 |
| R 1.3, vocabulario controlado; R 1.4, plantilla de datos | Entrada del extractor y esquema `$jsonSchema` de salida |

## 3. Enfoque

Hay tres tipos de caso, según lo que necesitan para ejecutarse:

| Tipo | Cómo se ejecuta | Marcador de pytest |
|---|---|---|
| **U**, unitario con datos de prueba | Respuestas de los portales simuladas con `respx` y reloj controlado; sin red ni base de datos | ninguno |
| **I**, integración | Contra MongoDB y el servicio de embeddings del `compose.yaml`, en la base `ingesta_pruebas` | `integracion` |
| **V**, en vivo | Dentro de una campaña real contra los portales; la evidencia son el registro y la colección `ejecuciones` | `en_vivo` |

Los casos U e I no consultan los portales: así se prueba el protocolo sin generar tráfico adicional sobre los sitios. Los datos de prueba (`pruebas/fixtures/`) son sintéticos o recortes anonimizados del piloto de R 2.1, sin datos de personas naturales. Un caso puede verificar varias condiciones, y solo se aprueba si se cumplen todas.

## 4. Entorno

| Elemento | Configuración |
|---|---|
| Servicios | `compose.yaml`: MongoDB 8.0.32, TEI 1.9 con `intfloat/multilingual-e5-large` (revisión fijada, fp16, GPU) |
| Aplicación | Imagen `ingesta:dev`, Python 3.13, dependencias bloqueadas en `uv.lock` |
| Base de datos | `ingesta_pruebas`, que se vacía al inicio de cada ejecución; la base `ingesta` nunca se usa en pruebas |
| Parámetros | `config/parametros.toml` de la versión probada |
| Vocabulario | Versión exportada del xlsx de R 1.3, anotada en cada ejecución |

Ejecución: `docker compose run --rm ingesta pytest -m "not en_vivo" --junitxml=exportaciones/pruebas_AAAA-MM-DD.xml`. Los casos V se verifican sobre la campaña real.

## 5. Casos de prueba

Convenciones: **C** = compromiso del protocolo de R 2.1; **R** = riesgo de R 2.1; **I** = decisión de implementación de R 2.3; **§** = sección del Anexo J.

### 5.1 Protocolo de recolección

| ID | Traza | Condición y entrada | Resultado esperado | Tipo |
|---|---|---|---|---|
| CP-01 | C1 | `robots.txt` de ambos portales sin cambios en las rutas vigiladas | La campaña continúa; el texto y la huella de cada `robots.txt` quedan en `ejecuciones` | U |
| CP-02 | C1, §9 | `robots.txt` que prohíbe una ruta vigilada (`Disallow: /api/avisos/`) | La campaña no arranca: no sale ninguna solicitud a los portales y la corrida queda fallida con el motivo | U |
| CP-03 | C2, C5 | Campaña completa con transporte simulado | Todas las solicitudes llevan el User-Agent de navegador configurado; ninguna lleva `Authorization` ni cookies de sesión | U |
| CP-04 | C3, R2 | Aviso de Computrabajo cuyo texto visible difiere del bloque `JobPosting` | Lo guardado proviene del `JobPosting` (Computrabajo) o del JSON de la interfaz (Bumeran), nunca del HTML visible | U |
| CP-05 | C3, I6 | Página de aviso de Computrabajo sin bloque `JobPosting` | Se cuenta como fallido de la fuente; no se lee el HTML de respaldo ni se escribe en `avisos_crudos` | U |
| CP-06 | C4 | Veinte solicitudes seguidas con reloj controlado | Entre dos solicitudes pasan al menos 2 s y nunca hay dos en curso | U, V |
| CP-07 | C4 | Con `dia_permitido` fijado en un día (por defecto es «cualquiera», I24), campaña nueva iniciada otro día; después, un reproceso ese mismo día | La campaña se rechaza sin consultar los portales; el reproceso sí se ejecuta, porque no usa la red | U |
| CP-08 | C6, I12 | Aviso cuya descripción incluye un correo y un celular de una persona natural | Ninguno de los dos aparece en `avisos_crudos`, `ofertas_laborales` ni `ofertas_descartadas` | I |
| CP-09 | C7 | Repositorio y servicios después de una campaña; exportación de la muestra | `git ls-files` no contiene `.env` ni datos; el hook de pre-commit los bloquea; los puertos escuchan solo en 127.0.0.1; la muestra exportada recorta la descripción | U, V |

### 5.2 Adquisición

| ID | Traza | Condición y entrada | Resultado esperado | Tipo |
|---|---|---|---|---|
| CP-10 | R5, §9 | Una solicitud responde 503 tres veces y luego 200 | Tres reintentos con esperas de 2, 4 y 8 s; el aviso se obtiene y no cuenta como fallido | U |
| CP-11 | R5, R1 | Tres rechazos 403 seguidos; en otra prueba, diez rechazos acumulados no consecutivos | La fuente se detiene en ambos casos y el corte queda registrado con su causa | U |
| CP-12 | CI-5 | Búsqueda de Bumeran en tres páginas, con `total` = 45 | Se recorren las tres páginas, se obtienen 45 avisos y `id` pasa a `fuente.id_aviso` | U |
| CP-13 | I2 | Un aviso de Bumeran presente en el mapa de sitio y otro ausente | El primero toma la URL del mapa de sitio; el segundo, la del patrón, y se contabiliza en las métricas | U |
| CP-14 | I9 | URL de Computrabajo con el hexadecimal de 32 caracteres al final; otra truncada | El identificador se extrae del hexadecimal; la URL truncada cuenta como fallida | U |
| CP-15 | §7 | Aviso nuevo de cada portal | `avisos_crudos` guarda portal, identificador, contenido original (JSON en Bumeran; bloque `JobPosting` en Computrabajo), fecha de extracción y huella, antes de cualquier transformación y sin el HTML completo | I |

### 5.3 Limpieza, pertinencia y deduplicación

| ID | Traza | Condición y entrada | Resultado esperado | Tipo |
|---|---|---|---|---|
| CP-16 | I4, §5 | Descripción con etiquetas HTML y entidades; aviso de Bumeran con secciones Indispensables, Deseables y Habilidades blandas | `descripcion` queda en texto plano; ninguna unidad de requisito cruza de una sección a otra | U |
| CP-17 | R3 | Tres avisos con 1, 2 y 3 competencias técnicas literales; un cuarto con 1 técnica y 3 transversales | El de 1 técnica y el cuarto se descartan con motivo `no_TI`; los de 2 y 3 continúan | U |
| CP-18 | R4 | Mismo aviso en Bumeran y en Computrabajo, con 5 días de diferencia y Jaccard ≥ 0,80 | Sobrevive el primero visto; el segundo va a `ofertas_descartadas` con motivo `duplicado` y el identificador del sobreviviente | U |
| CP-19 | R4 | Dos avisos de la misma empresa y título: uno a 40 días; otro dentro de la ventana pero con Jaccard < 0,80 | Ninguno se marca como duplicado | U |

### 5.4 Extracción de competencias

| ID | Traza | Condición y entrada | Resultado esperado | Tipo |
|---|---|---|---|---|
| CP-20 | §6 | «Experiencia en SQL Server y JavaScript» | Se extraen SQL Server y JavaScript; no SQL ni Java | U |
| CP-21 | §6 | «Área de RRHH», «go-live del proyecto», «lenguaje R», «desarrollo en Go» | Solo se extraen R y Go en las dos últimas, por la regla de contexto y la sensibilidad a mayúsculas | U |
| CP-22 | §6, B3 | Texto que contiene una variante descriptiva («backups») y ninguna literal | La vía literal no extrae nada: la variante descriptiva solo participa en la vía semántica | U |
| CP-23 | D11 | «Experiencia con EKS» | Dos entradas de competencia: AWS y Kubernetes | U |
| CP-24 | R 1.3 | «Phyton y Postgree» | Se extraen Python y PostgreSQL; la anotación entre paréntesis del xlsx no forma parte de la variante | U |
| CP-25 | §6 | Unidad sin coincidencia literal con puntaje sobre el umbral; otra por debajo | La primera aporta la competencia; la segunda se encola en `candidatos_competencia` con tramo, unidad, aviso, término más cercano y puntaje | I |
| CP-26 | §7 | Aviso cuyas menciones solo generan candidatos | Se descarta con motivo `sin_competencias` y el detalle lista los tramos encolados | I |
| CP-27 | I14 | Competencia transversal ubicada bajo «Indispensables» y técnica bajo «Habilidades blandas» | `tipo` sale de la rama de la categoría (transversal y técnica), no de la sección | U |
| CP-28 | I5 | «Python avanzado», «conocimientos básicos de Docker», «Git», «3 años de experiencia en Java»; «Habilidad avanzada en Wireshark»; marcador a más de 100 caracteres; título en mayúsculas pegado a la frase anterior | `nivel_requerido`: avanzado, básico, ausente, ausente; avanzado; ausente; el marcador de la sección siguiente no califica la competencia anterior | U |

### 5.5 Validación, escritura y reproceso

| ID | Traza | Condición y entrada | Resultado esperado | Tipo |
|---|---|---|---|---|
| CP-29 | R 1.4 | Oferta completa; otra sin `fecha_publicacion` | La primera se escribe en `ofertas_laborales`; la segunda es rechazada por el validador (código 121) y va a descartes con motivo `esquema` | I |
| CP-30 | I3 | Aviso confidencial de Bumeran | Se escribe con `empresa.nombre` = «Confidencial», el texto que da el portal | I |
| CP-31 | I8, §9 | La misma campaña simulada, ejecutada dos veces | La segunda no crea documentos nuevos en ninguna colección; existe el índice único (portal, id_aviso) | I |
| CP-32 | §7 | Exportación del xlsx de R 1.3 | JSON versionado con 322 términos, 26 categorías con su rama, 626 variantes literales y 1.929 descriptivas (versión vigente de R 1.3) | U |
| CP-33 | I7, §9 | Reproceso tras un cambio de vocabulario que lleva un aviso de descartes a publicado y otro al revés | Cada aviso queda solo en su nuevo destino y se borra del anterior; el reproceso no hace ninguna solicitud de red | I |
| CP-34 | §13, C3 de R 2.2 | Candidato aprobado por el revisor | El término entra al vocabulario con versión nueva y el reproceso recupera la competencia en los avisos ya ingresados | I |

### 5.6 Registro y escenarios de operación

| ID | Traza | Condición y entrada | Resultado esperado | Tipo |
|---|---|---|---|---|
| CP-35 | §9 | Cualquier corrida | `ejecuciones` y el archivo de registro contienen vistos, nuevos y fallidos por fuente, duplicados, descartes por motivo, competencias por aviso, candidatos, versión del vocabulario, parámetros usados, duración y estado | I |
| CP-36 | §9 | Tasas de éxito por fuente de 49 % y de 50 % | La primera marca la corrida como fallida; la segunda no | U |
| CP-37 | §13 | Campaña normal completa sobre datos de prueba | Cada aviso termina publicado o descartado con motivo; los ya conocidos no generan escrituras | I |
| CP-38 | §13, R1 | Bumeran devuelve 403 en todas las solicitudes | Bumeran se detiene tras el corte; Computrabajo termina su recorrido; la corrida queda fallida | I |
| CP-39 | Todos | Primera campaña real completa | Termina y deja su documento en `ejecuciones`, el archivo de registro y la muestra exportada; los intervalos del registro confirman CP-06 | V |

### 5.7 Funciones añadidas durante la implementación

Estas funciones no estaban en la versión 1.0 del plan. Sus pruebas ya existían y se renombraron con el identificador del caso.

| ID | Traza | Condición y entrada | Resultado esperado | Tipo |
|---|---|---|---|---|
| CP-40 | I30 | Aviso con «¿Qué ofrecemos?», «Horario:», presentación de la empresa y, después, un título de requisitos o una sección de Bumeran | Las unidades entre el título de beneficios y el siguiente título de requisitos quedan en la sección «Beneficios y empresa»; la vía semántica no las evalúa, pero el diccionario sí | U |
| CP-41 | I29, I30 | Vía semántica con grupos nominales de menos de 4 palabras, un vocabulario con términos canónicos y descriptivas, y el interruptor apagado | Solo se compara con variantes descriptivas; los grupos cortos no se comparan; bajo `umbral_candidato` no se encola; apagada, no se consulta el servicio de embeddings y la ejecución lo anota | U, I |
| CP-42 | Vía léxica | Unidades con tecnologías ausentes del vocabulario, palabras del español poco frecuentes, inglés común, CamelCase pegado y versiones | Solo quedan como candidatas las palabras ajenas al vocabulario, al español y al inglés común; las contiguas forman un tramo; se encolan con origen «lexico», también en unidades con coincidencia literal, y nunca asignan competencias | U |
| CP-43 | Vía léxica | El mismo tramo léxico en varios avisos; se aprueba y, en otra prueba, se rechaza | El panel lo muestra agrupado con su número de avisos; aprobar resuelve todos sus avisos; el rechazo pasa a `lexicos_rechazados` y el tramo no vuelve a encolarse | I |
| CP-44 | Decisiones en lote | Exportación de la cola a CSV y Excel; archivo con aprobaciones, rechazos, filas erróneas, ya revisadas y la misma habilidad nueva dos veces | El CSV conserva las tildes y el Excel trae desplegables; las filas válidas se aplican y las erróneas u omitidas se informan sin bloquearlas; todas las aprobaciones generan una sola versión del vocabulario | I |
| CP-45 | I26, I27 | Publicación manual de un aviso descartado; otra con un término ausente del vocabulario; categoría nueva creada desde el panel | La primera se respeta en los reprocesos hasta quitarla; la segunda se rechaza; la categoría nueva admite términos con su rama | I |
| CP-46 | I25 | Campaña sobre datos de prueba; reproceso de un solo aviso tras un cambio de vocabulario | La traza guarda unidades, coincidencias con su vía y puntaje, candidatos y destino; el panel la muestra con las coincidencias resaltadas y el HTML escapado; el reproceso del aviso aplica el vocabulario nuevo | U, I |
| CP-47 | I23, I24 | Corrida de un solo portal, con límite de avisos, un lunes; una ejecución abierta cuyo proceso ya terminó | Solo se consulta el portal elegido y se corta al llegar al límite; el día no impide la campaña; la ejecución abandonada queda como «interrumpida» y no bloquea una corrida nueva | I |
| CP-48 | I21, I28 | Aviso con título y emojis en el título y la descripción | El título es la primera unidad de requisito; los emojis no llegan a la oferta, pero el crudo los conserva | U |

## 6. Cobertura por componente

| Componente (Anexo J §5) | Casos |
|---|---|
| Iniciador de campaña | CP-07, CP-33, CP-39, CP-47 |
| Verificador de `robots.txt` | CP-01, CP-02 |
| Clientes de fuente | CP-03 a CP-06, CP-10 a CP-14, CP-38 |
| Repositorio de crudo | CP-08, CP-15 |
| Normalizador y segmentador | CP-16, CP-40, CP-48 |
| Filtro de pertinencia | CP-17 |
| Deduplicador | CP-18, CP-19 |
| Extractor de competencias | CP-20 a CP-28, CP-41, CP-42 |
| Gestor de descartes y cola de candidatos | CP-17, CP-18, CP-25, CP-26, CP-29, CP-34, CP-43 |
| Validador y escritor | CP-29 a CP-31 |
| Registro de ejecución y trazas | CP-35, CP-36, CP-46 |
| Panel de gestión | CP-43 a CP-47 |

En total hay 48 casos. Los siete compromisos del protocolo tienen al menos un caso (CP-01 a CP-09), igual que los riesgos R1 a R5 y los escenarios del §13 (CP-37, CP-38, CP-34 y CP-45).

### Implementación de los casos (2026-09-27)

| Casos | Archivo de prueba | Tipo |
|---|---|---|
| CP-01, CP-02 | `test_robots.py`; CP-02 también en `test_campana.py` | U, I |
| CP-03, CP-06, CP-10, CP-11 | `test_cliente_http.py` | U |
| CP-04, CP-05, CP-12, CP-13, CP-14 | `test_fuentes.py` | U |
| CP-07, CP-08, CP-15, CP-26, CP-29 a CP-31, CP-33 a CP-35, CP-37, CP-38 | `test_campana.py` (y CP-30 en `test_avisos.py`) | I |
| CP-09 | `test_repositorio.py` (estático) y `test_muestra.py` (muestra recortada) | U, I |
| CP-16 | `test_normalizacion.py` | U |
| CP-17 | `test_filtro.py` | U |
| CP-18, CP-19 | `test_deduplicacion.py` | U |
| CP-20 a CP-24 | `test_extraccion_literal.py` | U |
| CP-25 | `test_extraccion_semantica.py` (unitaria) y `test_embeddings.py` (modelo real) | U, I |
| CP-27 | `test_extractor.py` | U |
| CP-28 | `test_nivel.py` | U |
| CP-32 | `test_vocabulario.py` | U |
| CP-36 | `test_estado_corrida.py` | U |
| CP-39 | Campaña real del 2026-10-04, pendiente de revisión del tesista | V |
| CP-40 | `test_normalizacion.py`, `test_extractor.py` | U |
| CP-41 | `test_extraccion_semantica.py`, `test_extractor.py`, `test_campana.py`, `test_panel_config.py` | U, I |
| CP-42, CP-43 | `test_extraccion_lexica.py` | U, I |
| CP-44 | `test_importacion_decisiones.py`, `test_panel_datos.py` | I |
| CP-45, CP-47 | `test_gestion.py` | I |
| CP-46 | `test_gestion.py`, `test_panel_datos.py`, `test_panel_app.py` | U, I |
| CP-48 | `test_avisos.py`, `test_normalizacion.py` | U |

Los nombres de las funciones de prueba empiezan con el identificador del caso (`test_cp20_...`); las de CP-16 y algunas auxiliares no llevan prefijo. La última ejecución está en la sección 9.

## 7. Criterio complementario: calidad de la extracción

Se toman treinta ofertas al azar de la primera campaña real y en cada una se anotan a mano las competencias que deberían extraerse. La coincidencia es laxa: un tramo cuenta como acierto si se solapa con la mención y apunta al mismo término canónico. Con esa anotación se calculan precisión, exhaustividad y F1 (§12 del Anexo J). El valor de referencia es F1 ≥ 0,70; el resultado se reporta junto al de los casos de prueba y no cambia el indicador de la Tabla 2. Con la misma muestra se calibra el umbral de similitud, que hoy figura como provisional en `config/parametros.toml`.

## 8. Criterios de ejecución

| Criterio | Regla |
|---|---|
| Entrada | Servicios sanos (`docker compose ps`), vocabulario exportado y parámetros revisados |
| Aprobación | Todos los casos ejecutados y aprobados por el tesista (100 %, Tabla 2) |
| Caso fallido | Se registra el defecto, se corrige y se vuelve a ejecutar la batería automatizada completa, no solo el caso |
| Suspensión | Si un portal bloquea durante una prueba V, se detiene sin reintentar fuera del protocolo y se retoma en la campaña siguiente |

## 9. Registro de ejecución

| Fecha | Commit | Ejecutados | Aprobados | Fallidos | Observaciones |
|---|---|---|---|---|---|
| 2026-10-05 01:07 | `6dcf339` | 151 pruebas automatizadas: casos U e I (CP-01 a CP-38 y CP-40 a CP-48) | 151 | 0 | Informe JUnit en `exportaciones/pruebas_2026-10-05.xml`. Sin ejecutar como V: CP-39 y la parte en vivo de CP-06 y CP-09, que se verifican sobre la campaña del 2026-10-04 (`logs/campana_2026-10-05_001818.log`, colección `ejecuciones` y muestra `exportaciones/muestra_2026-10-05_0558.json`). **Aprobación del tesista: pendiente.** |

## Referencias

- ISO/IEC/IEEE. (2021). *ISO/IEC/IEEE 29119-3:2021. Software and systems engineering — Software testing — Part 3: Test documentation*.
