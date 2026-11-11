# Asistente de orientación en TI: criterios de diseño (R 3.2 interfaz y flujo / R 3.4 asistente)

Definidos con el tesista el 2026-11-10/11 e implementados en `src/ingesta/asistente/` (http://localhost:8502).
La sección «Estado de la implementación», al final, registra las decisiones tomadas al construirlo.

## Contexto
El asesor pidió ver el asistente funcionando. Partió de un MVP (commit `9bae0f5`).

El tesista no quiso un MVP desechable, sino un **producto semifinal** definido bien desde el inicio:
- cuentas de usuario;
- chats guardados;
- conversación con repreguntas;
- datos verificables.

Estos criterios serán la base para redactar después R3.1 (requerimientos) y R3.3 (arquitectura).

**Reglas del usuario:**
- Ninguna llamada real a la API sin permiso previo.
- La calidad va primero: no hace falta recortar el contexto. US$ 5 alcanzan para más de mil preguntas.

## 1. Casos de uso (de «R 2.4 - Preguntas de calibracion.md»)
Rol · habilidades · funciones · con requisitos exigidos · pregunta ambigua · fuera de dominio.

## 2. Conversación: intenciones
| Intención | Ejemplo | Cómo se resuelve |
|---|---|---|
| Nueva búsqueda | «¿Qué piden para backend con Java?» | El LLM interpreta → `buscar()` → el LLM redacta |
| Fuentes | «¿De dónde lo sacaste?» | El código muestra las ofertas de la respuesta anterior; no busca de nuevo (0 tokens) |
| Profundizar | «Háblame de la oferta 2» | El LLM recibe solo esa oferta (con su descripción completa) y la explica |
| Refinar | «¿Y si soy junior?», «¿solo las que piden inglés?» | Combina la consulta y los filtros anteriores con el ajuste y vuelve a buscar |
| Qué me falta | «Sé Python y SQL, ¿qué me falta para analista de datos?» | Busca el rol, el código resta del conteo lo que el usuario dijo saber y el LLM explica la brecha |
| Charla / fuera de dominio | «Hola», «Busco trabajo de cocinero» | Respuesta directa y amable, sin buscar |

- Comparar dos roles queda descartado.
- **Qué me falta:** muestra solo la brecha, es decir, las competencias pedidas que el usuario no
  mencionó, con su %. Nunca dice qué estudiar, en qué orden ni dónde, porque el título nuevo no
  incluye rutas de aprendizaje.
- **Sin perfil del estudiante:** el asistente solo sabe lo que el usuario dice dentro de cada
  conversación.

## 3. Respuestas
- **Estilo:** tono orientador, cercano y profesional, tuteando. Entre 150 y 250 palabras. Explica el
  porqué y cita [n].
- **El LLM nunca escribe cifras.** Marca la competencia como `{{Spring Boot}}`, y el código la
  reemplaza por la etiqueta `:blue-badge[Spring Boot · 74 %]` con el conteo real. Una marca que no
  está en el conteo queda como texto plano.
- **Solo datos del contexto:** no inventa empresas, sueldos ni requisitos. Avisa si la evidencia es
  escasa o si se relajaron los filtros.
- **Respuesta en streaming:** el texto aparece mientras se genera, como en cualquier chat de IA. Las
  marcas completas se reemplazan por etiquetas sobre la marcha.

## 4. Pantalla (Streamlit pulido)
Patrones de Perplexity y de guías de UX de chat con citas.

**Entrada:**
- Pestañas «Iniciar sesión» y «Crear cuenta» (usuario y contraseña).
- Un texto breve de qué hace el asistente y de que no guarda datos personales.

**Barra lateral, como un chat de IA de toda la vida:**
- botón «＋ Nueva conversación»;
- lista de conversaciones del usuario, de la más reciente a la más antigua, con título y opción de
  borrar;
- «⭐ Mis ofertas guardadas»;
- contador de la sesión: tokens y US$ (solo cuenta, no corta);
- «Ofertas actualizadas al dd/mm/aaaa» y botón «Cerrar sesión».

**Conversación vacía:** saludo y 4–6 preguntas de ejemplo como botones, una por caso de uso.

**Cada respuesta del asistente:**
1. **Texto del LLM**, con etiquetas de datos.
2. **Recuadro con borde:** «📊 Datos de las ofertas · calculado por el sistema sobre N ofertas
   (no lo genera la IA)», con barras de las ~8 competencias más pedidas. En «qué me falta», el
   recuadro muestra la brecha.
3. **Fuentes visibles, sin plegar:** tarjetas de las ofertas citadas, cada una con título enlazado,
   empresa, portal, fecha y botón «⭐ Guardar».
4. **2–3 botones de repregunta**, solo en el último mensaje, fijos según el caso:
   - «¿De dónde sale esto?»
   - «Háblame de la oferta 1»
   - «¿Qué me falta?»
   - «¿Y para junior?»

Se elimina «Cómo se buscó».

## 5. Cuentas y datos guardados (MongoDB, base `ingesta`)
| Colección | Contenido |
|---|---|
| `usuarios` | Usuario (único, 3–30 caracteres), hash de la contraseña y fecha de creación. Sin correo ni nombre real |
| `conversaciones` | Id del usuario, título (la primera pregunta recortada, sin LLM), creada y actualizada |
| `turnos` | Ver detalle abajo |
| `ofertas_guardadas` | Id del usuario, portal, id del aviso y fecha (índice único por los tres primeros) |

Cada documento de `turnos` guarda:
- id de la conversación y orden;
- pregunta e intención;
- consulta y filtros;
- ids de las ofertas recuperadas y conteo;
- texto de la respuesta y citas;
- tokens, costo y segundos;
- modelo y versión del prompt.

Sirve para reabrir el chat y para la evaluación RAG y de sesgos sin repetir llamadas.

**Seguridad, sin dependencias nuevas:**
- La contraseña se guarda con `hashlib.scrypt` de la biblioteca estándar, con sal aleatoria, y se
  compara con `hmac.compare_digest`. Mínimo 8 caracteres.
- La sesión vive en `st.session_state`, así que al recargar la página hay que volver a entrar
  (decisión mía; las cookies quedan como mejora).
- Cada consulta filtra por el id del usuario: nadie ve los chats de otro.
- Todo sigue en `127.0.0.1`.

**Al reabrir una conversación** se reconstruye desde `turnos`, y las ofertas se vuelven a leer de
`ofertas_laborales` por sus ids. El estado de la última búsqueda queda disponible para seguir
repreguntando.

## 6. LLM: cómo busca en la base de conocimiento
Sigue V9 de R2.4: *tool calling*, validación contra el vocabulario de R1.3 y redacción. Se le agrega
un reintento acotado, a partir de la investigación hecha en la web, en HN y en la literatura de RAG
conversacional.

### Llamada 1: decidir (con herramientas, sin streaming)
La llamada recibe:
- las reglas;
- el catálogo completo de competencias, categorías, tipos y niveles;
- el historial;
- la pregunta.

El LLM elige una de estas opciones:

| Herramienta | Parámetros | La ejecuta el código |
|---|---|---|
| `buscar_ofertas` | `consulta` (reescrita como pregunta completa, resolviendo referencias del historial), `consulta_alternativa` (reformulación con otros términos, por ejemplo «automatizar despliegues» → «DevOps, CI/CD»), `competencias_exigidas`, `categorias`, `tipos`, `niveles` | `buscar()` de R2.4 |
| `calcular_brecha` | `puesto`, `competencias_conocidas` | Busca el puesto y resta lo conocido del conteo |
| `ver_oferta` | `numero` (de la respuesta anterior) | Lee esa oferta completa de MongoDB |
| `mostrar_fuentes` | — | Muestra las ofertas de la respuesta anterior, sin una segunda llamada |
| *(ninguna)* | — | Responde directo (charla o fuera de dominio) |

Los argumentos se validan contra el catálogo: lo que no está en el vocabulario se descarta.

### Reintento acotado (máximo 2 búsquedas, sin otra llamada al LLM)
Si la búsqueda trae menos de `minimo_ofertas` (10), se repite con `consulta_alternativa`, y queda la
búsqueda que trajo más ofertas. Si todavía hay 0 ofertas y había filtros, se busca sin ellos y se
avisa.

### Llamada 2: redactar (en streaming)
El prompt depende del caso: `respuesta.md`, `brecha.md` u `oferta.md`. Recibe el contexto preparado
por el código, no la conversación de las herramientas.
- **Contexto de la redacción:**
  - 8 ofertas;
  - fragmento de 450 caracteres;
  - 15 competencias por oferta;
  - las 15 más frecuentes del conteo;
  - historial de los últimos 6 mensajes.
  La literatura indica que más fragmentos pueden meter ruido, por eso al LLM le llegan 8 ofertas
  aunque el conteo se hace sobre las 50.
- **Los textos de las ofertas son datos, no instrucciones:** el prompt lo dice explícitamente
  (defensa contra instrucciones incrustadas en un aviso).
- **Prompts en archivos versionados** (`src/ingesta/asistente/prompts/*.md`, con versión en el
  encabezado). Se guardan con cada turno y quedan listos para un anexo de la tesis.
- **Reranker:** no se implementa. Se anota en `otros/Posibles mejoras.md` (decisión del usuario).
- **Parámetros** en `config/parametros.toml`, sección `[asistente]`: número de ofertas, caracteres
  por fragmento, mensajes de historial, precios por millón de tokens (0,20 y 1,20) y nombre del
  modelo por defecto.
- **Tokens:** se registran por turno desde `usage`, incluidos los de razonamiento si la API los
  reporta.
- **Errores:** si la API falla, se muestra un mensaje con «Reintentar» y el turno no se guarda como
  respondido.

## 7. Arquitectura del código
El motor del asistente es independiente de Streamlit, así que más adelante se le puede poner una API
sin reescribirlo.
- **`asistente/servicio.py`:** motor (intenciones, búsqueda, brecha, redacción y etiquetas). Reutiliza
  `buscar()` y `Filtros` de `conocimiento/busqueda.py`.
- **`asistente/llm.py`:** `ClienteLLM` con `completar(tools=...)`, que devuelve el texto o las
  llamadas a herramientas, y `completar_stream()`, que devuelve el uso de tokens al final.
- **`asistente/herramientas.py`:** los esquemas de las 4 herramientas, la validación de argumentos y
  su ejecución.
- **`asistente/cuentas.py`:** registro, verificación y hash de contraseñas.
- **`asistente/historial.py`:** conversaciones, turnos y ofertas guardadas, con sus índices en
  `bd.preparar`.
- **`asistente/prompts/`:** `interpretacion.md`, `respuesta.md` y `oferta.md`.
- **`asistente/app.py`:** solo interfaz (login, barra lateral, chat, tarjetas y botones).
- **`config.py` y `parametros.toml`:** sección `[asistente]`.
- **`pruebas/test_asistente*.py`:** con LLM falso y una base de pruebas de MongoDB:
  - los botones no llaman al LLM;
  - el reintento usa `consulta_alternativa` y se detiene en 2 búsquedas;
  - argumentos fuera del catálogo descartados;
  - fuentes reutiliza las ofertas anteriores;
  - etiquetas conocidas y desconocidas;
  - la brecha excluye lo conocido;
  - profundizar envía una sola oferta;
  - refinar combina la consulta anterior;
  - hash y verificación de la contraseña, usuario duplicado;
  - aislamiento entre usuarios;
  - reabrir una conversación;
  - guardar y quitar una oferta;
  - el costo se acumula.
- **`docs/asistente_criterios_diseno.md`:** este documento, base de R3.1, R3.2 y R3.3.

**Prioridad si el tiempo aprieta antes de la demo:**
1. Conversación y pantalla de respuesta.
2. Cuentas e historial.
3. Ofertas guardadas.

## 8. Verificación
1. Sin API: correr `pytest` (toda la suite) y `ruff` en el contenedor.
2. Sin API: en el navegador, en modo sin LLM, probar crear una cuenta, entrar, preguntar, abrir una
   fuente, guardar una oferta, cerrar sesión, entrar con otra cuenta (no ve lo del primero) y reabrir
   un chat.
3. **Con permiso del usuario, lote 0:** 1 llamada («hola») para comprobar el nombre del modelo, los
   parámetros, el streaming y los tokens de razonamiento.
4. **Con permiso, lote 1, el guion de la demo:** unas 10 llamadas, < US$ 0,05, con el reporte de tokens
   de cada una.
   - **A.** «Quiero ser desarrollador backend con Java, ¿qué piden?» → botón «¿De dónde sale esto?»
     → «Háblame de la oferta 1» → «Sé Java y SQL, ¿qué me falta?»
   - **B.** «Me gusta proteger sistemas y detectar vulnerabilidades» → «¿Y si soy junior?»
   - **C.** «Busco trabajo de cocinero».
5. Ajustar los prompts según lo observado; cada ajuste que requiera llamadas pide permiso de nuevo.
6. Commit y push en ingesta. En el tablero, R3.2 y R3.4 pasan a «en curso». Anotar el reranker en
   `otros/Posibles mejoras.md`.

## Fuentes de la investigación
- [Shekhar Gulati, «Query Rewriting in RAG Applications»](https://shekhargulati.com/2024/07/17/query-rewriting-in-rag-applications/)
- [Alhena, «Query rewriting before retrieval»](https://alhena.ai/blog/query-rewriting-before-retrieval-multi-turn-rag/)
- [Mastra, «Agentic RAG»](https://mastra.ai/articles/agentic-rag)
- HN: [Production RAG, 5M docs](https://news.ycombinator.com/item?id=45645349) ·
  [$100 RAG](https://news.ycombinator.com/item?id=38833087) ·
  [A year of building with LLMs](https://news.ycombinator.com/item?id=40534293)
- [Kunal Ganglani, «RAG context window limits»](https://www.kunalganglani.com/blog/rag-context-window-limitations)
- UX de citas: [SaaSFrame](https://www.saasframe.io/patterns/citations-sources) ·
  [Perplexity teardown](https://aiuxplayground.com/teardowns/perplexity/citations) ·
  [Confident wrong answers](https://mspk.substack.com/p/designing-for-confident-wrong-answers)

## Estado de la implementación (2026-11-11)
Implementado según este documento. Decisiones tomadas al construirlo, que no estaban en el plan:
- **Los turnos guardan una copia de las ofertas recuperadas**, no solo sus ids, para que un chat se
  reabra tal como se vio aunque la oferta cambie o se borre en un reproceso.
- **Prompts:** `decision.md` (llamada con herramientas), `respuesta.md`, `brecha.md` y `oferta.md`,
  todos en la versión 1. El identificador `nombre@versión` se guarda en cada turno.
- **El botón «¿Qué me falta?»** no llama al LLM: pide al usuario sus competencias. Su respuesta
  escrita («sé Java y SQL») pasa por la decisión, que llama a `calcular_brecha`.
- **Borrar una conversación** pide confirmación en la barra lateral.
- **El modo sin LLM** responde con una plantilla que usa las mismas etiquetas de datos.

**Verificado sin API:**
- 30 pruebas nuevas (`pruebas/test_asistente.py`, `pruebas/test_asistente_cuentas.py`) y la suite
  completa (222).
- Recorrido en el navegador: crear una cuenta, preguntar, ver las fuentes, guardar una oferta,
  pedir el detalle de una oferta, «¿Qué me falta?», reabrir el chat y ver las ofertas guardadas.

**Pendiente:** los lotes con la API real (pasos 3–5 de la verificación), que esperan el permiso del
tesista.

## Pruebas con la API real (2026-11-11)
- **Lote 0** («hola»): la API rechazó las herramientas con `reasoning_effort` por defecto (HTTP 400).
  Desde entonces la decisión usa `"none"` (`razonamiento_decision` en `parametros.toml`). Con eso:
  2.355 tokens de entrada, 34 de salida y US$ 0,0005.
- **Lote 1** (guion A/B/C de la verificación): 10 llamadas, US$ 0,0079, unos US$ 0,0017 por pregunta
  con búsqueda. Detalle en `revision/Asistente - Lote 1 de pruebas (2026-11-11).md` (carpeta de la
  tesis).
  - Las 7 respuestas eligieron la herramienta correcta.
  - El LLM no escribió ningún porcentaje y no hubo marcas fuera del conteo ni citas inválidas.
- **Ajustes posteriores** (sin API, con pruebas):
  1. `decision.md` v2: el filtro `tipos` solo se usa si se pide expresamente; el LLM lo agregaba sin
     motivo.
  2. Se quita un símbolo suelto tras el punto final (apareció un «Δ»).
  3. Las citas seguidas [2][3] se separan con un espacio.

  El ajuste 1 queda por confirmar con una llamada real.
