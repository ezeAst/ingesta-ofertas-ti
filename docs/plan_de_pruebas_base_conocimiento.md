# Plan de pruebas de carga, embeddings y recuperación semántica (R 2.4)

**Resultado:** R 2.4, base de conocimiento construida a partir de la información estructurada, que asegura su almacenamiento, actualización y disponibilidad para el asistente conversacional.
**Medio de verificación (Tabla 2):** base de datos de conocimiento poblada, reporte de registros almacenados y plan de pruebas de carga, embeddings y recuperación semántica.
**Indicador:** 100 % de casos de prueba ejecutados y aprobados por el tesista.
**Autor:** Sebastián Antonio Martínez Toledo · **Fecha:** 25 de octubre de 2026 · **Versión:** 1.0

La estructura sigue, en forma abreviada, la plantilla de ISO/IEC/IEEE 29119-3:2021, igual que el plan de R 2.3 (`plan_de_pruebas_funcionales.md`).

## 1. Alcance

Se prueba la base de conocimiento diseñada en «R 2.4 - Decisiones de diseno.md» (V1 a V18):
- la carga de `ofertas_laborales` en Qdrant, con un punto por oferta y los vectores `titulo`, `competencias` y `fragmentos`;
- su sincronización incremental y automática tras cada campaña;
- la función `buscar()` que usará el asistente (R 3).

«Pruebas de carga» significa carga de datos, no rendimiento con usuarios concurrentes (V12). Quedan fuera la calibración de umbrales (V14), la comparación de modelos de *embeddings* (V15) y la evaluación de la calidad de las respuestas del asistente (R 3.4).

## 2. Enfoque y entorno

| Tipo | Cómo se ejecuta | Marcador de pytest |
|---|---|---|
| **U**, unitario | Embebedor de palabras (bolsa de palabras con *hashing*), sin servicios | ninguno |
| **I**, integración | MongoDB (base `ingesta_pruebas`), Qdrant (colección `ofertas_pruebas`) y TEI reales del `compose.yaml` | `integracion` |
| **R**, sobre la base real | Carga de las ofertas reales de la base `ingesta` en la colección `ofertas` | — |

En los casos U e I, las ofertas son sintéticas y el embebedor de palabras hace que cada resultado sea predecible: dos textos se parecen solo si comparten palabras. El entorno es el de R 2.3, más Qdrant 1.19.1 con API key y puertos en 127.0.0.1. Un caso solo se aprueba si se cumplen todas sus condiciones.

## 3. Casos de prueba

### 3.1 Carga

| ID | Traza | Condición y entrada | Resultado esperado | Tipo |
|---|---|---|---|---|
| BC-05 | V1, V2, V6 | Tres ofertas en MongoDB y una colección vacía | Tres puntos con los tres vectores; `fragmentos` con al menos un vector; el payload tiene portal, id, huella y los textos de los fragmentos | I |
| BC-06 | V10 | Segunda sincronización sin cambios | No crea, no actualiza ni borra, y no llama al servicio de *embeddings* | I |
| BC-07 | V10 | Se cambian las competencias de una oferta | Solo esa oferta se actualiza y su huella coincide con la nueva | I |
| BC-08 | V10 | Se borra una oferta en MongoDB | Su punto sale de Qdrant | I |
| BC-09 | V11 | Sincronización con `--todo` | La colección se reconstruye desde cero | I |
| BC-10 | V11, V16 | Corrida de vectorización | Queda en `ejecuciones` con modo, estado, creadas/actualizadas/borradas y duración | I |
| BC-11 | V11 | Campaña con Qdrant caído | La campaña conserva su estado; `base_conocimiento.estado = "desactualizada"` | I |
| BC-22 | V10, V15 | Cambia el modelo de *embeddings*; la colección tiene otra dimensión | Se recalculan todas las ofertas en vez de mezclar vectores de dos modelos; con otra dimensión, la sincronización se detiene y pide `--todo` | I |
| BC-23 | V11 | Campaña o reproceso que no pudo actualizar Qdrant | El resumen de la CLI y el panel muestran que la base quedó desactualizada | I |
| BC-20 | V1, V16 | Carga completa de la base real | Puntos en Qdrant = documentos en `ofertas_laborales`; una segunda corrida no cambia nada | R |

### 3.2 *Embeddings*

| ID | Traza | Condición y entrada | Resultado esperado | Tipo |
|---|---|---|---|---|
| BC-01 | V10 | Mismo aviso dos veces; mismo id en dos portales | El id del punto es estable y distingue el portal | U |
| BC-02 | V10 | Cambian las competencias o solo la fecha de extracción | La huella cambia en el primer caso y no en el segundo | U |
| BC-03 | V2, I15 | Oferta con una competencia repetida | Textos `passage: <título>` y `passage: <título>. Competencias: …` sin repetidos | U |
| BC-04 | V3 | Descripción con beneficios, larga, sin unidades útiles o con una frase muy larga | Sin «Beneficios y empresa»; fragmentos ≤ límite con solapamiento de una unidad; el título como respaldo; la frase larga queda sola | U |
| BC-21 | V3, I15 | Conteo de tokens con el TEI real | El tokenizador del modelo cuenta `passage: Python` entre 3 y 10 tokens | I |

### 3.3 Recuperación semántica

| ID | Traza | Condición y entrada | Resultado esperado | Tipo |
|---|---|---|---|---|
| BC-12 | V4, V18 | Consulta por rol con `via="titulo"` | La oferta con ese título queda primera | I |
| BC-13 | V4, V6 | Consulta por habilidades (`competencias`) y por funciones (`fragmentos`) | Gana la oferta esperada; el fragmento citado es el más parecido, no otro de la misma oferta | I |
| BC-14 | V18, V9 | Consulta cuya mejor oferta por título es distinta de la mejor por competencias y por fragmentos; `via` inválida; consulta vacía | Con RRF gana la oferta que encabeza dos de las tres listas; los dos últimos casos se rechazan | I |
| BC-15 | V7 | Filtro por competencia; filtro sin ofertas | Solo se ordenan las ofertas que dejó MongoDB; sin ofertas no se consulta Qdrant | I |
| BC-16 | V4, V13 | Búsqueda con menos ofertas que `minimo_ofertas` | Conteo de competencias hecho en código y ordenado; `suficiente = False` | I |
| BC-17 | V13, V18 | Umbral de 0,99 en los tres vectores; después, solo en `competencias` y `fragmentos` | Primero no sale ninguna oferta. Después, la fusión reproduce el orden del vector `titulo`, lo que prueba que el corte se aplica dentro de cada vector | I |

### 3.4 Interfaz

| ID | Traza | Condición y entrada | Resultado esperado | Tipo |
|---|---|---|---|---|
| BC-18 | V11 | Ayuda de la CLI; `vectorizar` con una corrida en curso | Lista `vectorizar` y `buscar`; la vectorización se niega (código 3) | I |
| BC-19 | V17 | Panel con datos de prueba | Muestra la pestaña «Base de conocimiento»; sin Qdrant muestra el error y sigue funcionando | I |

Además de los casos numerados, hay pruebas de apoyo: parámetros de `[base_conocimiento]`, conteo de tokens por lotes, conexión de Qdrant en las dependencias reales, `ingesta estado` con vectorizaciones y `estado_base` con y sin Qdrant.

## 4. Implementación

| Casos | Archivo de prueba |
|---|---|
| BC-01 a BC-04 | `pruebas/test_conocimiento_textos.py` |
| BC-05 a BC-09, BC-22 | `pruebas/test_conocimiento_sincronizacion.py` |
| BC-10, BC-11 | `pruebas/test_conocimiento_vectorizacion.py` |
| BC-12 a BC-17 | `pruebas/test_conocimiento_busqueda.py` |
| BC-18 | `pruebas/test_cli.py` |
| BC-19 | `pruebas/test_panel_app.py`, `pruebas/test_panel_datos.py` |
| BC-23 | `pruebas/test_cli.py`, `pruebas/test_panel_datos.py` |
| BC-20 | `ingesta vectorizar --todo` y `ingesta vectorizar` sobre la base real |
| BC-21 | `pruebas/test_embeddings.py` |

## 5. Reporte de registros almacenados (2026-10-25)

Las cifras de carga salen de la colección `ejecuciones` (modo `vectorizacion`). El tiempo de búsqueda se midió aparte, con 10 preguntas lanzadas con `buscar()`, y no queda guardado en `ejecuciones`. El reporte no incluye texto de los avisos (compromiso 7).

| Dato | Valor |
|---|---|
| Ofertas en `ofertas_laborales` | 2.529 (Bumeran 2.225; Computrabajo 304) |
| Puntos en Qdrant (colección `ofertas`) | 2.529 |
| Fragmentos cargados | 4.165 (1,65 por oferta) |
| Fragmentos que el modelo recorta (> 512 tokens; se cuentan fragmentos, no ofertas) | 8 |
| Carga completa (`--todo`) | 89,0 s (79,6 s al recalcular las 2.529 ofertas) |
| Sincronización sin cambios | 0,2 s |
| Búsqueda (10 preguntas, informativo) | 136 ms en promedio, 220 ms como máximo |

## 6. Registro de ejecución

| Fecha | Commit | Ejecutados | Aprobados | Fallidos | Observaciones |
|---|---|---|---|---|---|
| 2026-10-25 | ver `git log` (R 2.4) | 23 casos: la suite completa del repositorio (187 pruebas de R 2.3 y R 2.4, U e I) en verde y BC-20 sobre la base real | pendiente | 0 | Tres pruebas omitidas, previas a R 2.4: el xlsx de R 1.3 no está montado en `/resultados`. **Aprobación del tesista: pendiente.** |

## Referencias

- ISO/IEC/IEEE. (2021). *ISO/IEC/IEEE 29119-3:2021. Software and systems engineering — Software testing — Part 3: Test documentation*.
