# Mecanismo de ingesta de ofertas laborales (R 2.3 / R 2.4)

El código se versiona en GitHub (https://github.com/ezeAst/ingesta-ofertas-ti). El corpus en bruto, los registros, las exportaciones y las credenciales quedan fuera del repositorio (`.gitignore` y `pre-commit`) y no salen de la estación de trabajo (compromiso 7 de R 2.1).

- Diseño: `../resultados/Resultado 2.2 - Diseno del Mecanismo de Ingesta.md` (Anexo J)
- Decisiones de implementación: `../resultados/apoyo R 2.3/R 2.3 - Decisiones de implementacion.md`
- Plan de pruebas funcionales: [`docs/plan_de_pruebas_funcionales.md`](docs/plan_de_pruebas_funcionales.md)

## Arquitectura

Todo corre en Docker, orquestado con `compose.yaml`:

| Servicio | Imagen | Función | Puerto (solo 127.0.0.1) |
|---|---|---|---|
| `mongo` | `mongodb/mongodb-community-server:8.0.32-ubi9-slim` | Colecciones de la ingesta, con el validador `$jsonSchema` de R 1.4 | 27017 |
| `embeddings` | `ghcr.io/huggingface/text-embeddings-inference:89-1.9` | Sirve `intfloat/multilingual-e5-large` (revisión fijada, fp16) en la GPU | 8080 |
| `qdrant` | `qdrant/qdrant:v1.19.1-unprivileged` | Base vectorial de R 2.4 (perfil `r24`, con API key) | 6333, 6334 |
| `ingesta` | `ingesta:dev` (este `Dockerfile`) | Aplicación en Python 3.13; se ejecuta a demanda (perfil `cli`) | — |

Decisiones de infraestructura:

- **Un solo servicio de embeddings para R 2.3, R 2.4 y R 3.** Todos los vectores salen del mismo modelo y la misma revisión, así que son comparables. La imagen de la aplicación no carga PyTorch y pesa menos de 1 GB. No hay que mezclar estos vectores con los de `sentence-transformers`: TEI aproxima GeLU y los valores cambian levemente.
- **Datos en volúmenes con nombre** (`mongo_datos`, `hf_modelos`, `qdrant_datos`), no en carpetas de Windows. MongoDB y Qdrant advierten pérdida de datos con montajes sobre Windows/WSL.
- **Mínimo privilegio.** La aplicación usa un usuario de MongoDB con permisos solo sobre `ingesta` e `ingesta_pruebas`, creado por `infra/mongo/init/`. Los contenedores propios corren sin root y ningún puerto se abre a la red local.
- **Reproducibilidad.** Imágenes con versión fijada, dependencias bloqueadas en `uv.lock` (con hashes) y modelo de spaCy fijado por URL.

## Requisitos

- Docker Desktop con backend WSL 2 y un controlador NVIDIA reciente (probado: RTX 4060, controlador 591.86, Docker 29.2.1).
- Opcional: VS Code con la extensión Dev Containers.

## Primera vez

```powershell
copy .env.example .env      # y reemplazar las claves (alfanuméricas)
docker compose --profile r24 up -d
docker compose build ingesta
```

El usuario de la aplicación se crea solo la primera vez que se inicializa el volumen de MongoDB. La primera subida de `embeddings` descarga el modelo (~2,2 GB) y tarda unos minutos.

## Panel de gestión

`docker compose up -d` levanta también el panel en **http://localhost:8501** (Streamlit):

| Pestaña | Qué hace |
|---|---|
| Pipeline | Inicia una corrida en Bumeran, Computrabajo o ambos, con límite opcional de avisos; también reprocesa todo el crudo. Muestra la corrida en curso (se refresca cada 5 s, con el final del registro y un botón para detenerla) y el historial de ejecuciones. |
| Ofertas | Recorre los avisos uno por uno: **1 · cómo entró** (contenido original del portal), **2 · cómo se leyó** (unidades con coincidencias literales en verde y semánticas en ámbar, con su puntaje) y **3 · cómo quedó registrado** (documento de `ofertas_laborales` o motivo de descarte). |
| Descartes | Conteo por motivo, filtros y exportación a CSV. Por aviso: reprocesar, publicar a mano (la decisión se respeta en los reprocesos hasta quitarla) y añadir al diccionario una variante literal o descriptiva, una habilidad nueva o una categoría nueva. |
| Candidatos | Cola de revisión: aprobar como variante o como habilidad nueva, o rechazar. Dos orígenes: **por embeddings** (tramos dudosos de la vía semántica, con término cercano y puntaje) y **por descarte** (palabras que no son del vocabulario, ni del español, ni comunes en inglés, agrupadas por tramo con la cantidad de avisos que las mencionan; aprobar o rechazar resuelve todos sus avisos y el rechazo vale para los futuros). Parámetros en `[extraccion.via_lexica]`. **Decisiones en lote:** exportar a CSV o Excel (trae `id`, `decision`, `termino`, `descriptiva`, `nuevo_termino`, `categoria`; el Excel con desplegables), completar `decision` (variante, nueva, rechazar o vacía) e importar el archivo en «Importar decisiones»: se valida fila por fila y todas las aprobaciones crean una sola versión del vocabulario. |

Las corridas se lanzan como procesos aparte (`ingesta campana ...`), así que el panel no se bloquea; solo puede haber una a la vez. Cada cambio del diccionario crea una versión nueva en `vocabulario/` y se aplica al reprocesar.

## Uso

```powershell
docker compose up -d                                  # MongoDB + embeddings (Qdrant: --profile r24)
docker compose run --rm ingesta ingesta preparar      # colecciones, validador de R 1.4 e índices
docker compose run --rm ingesta ingesta vocabulario exportar   # xlsx de R 1.3 → vocabulario/vocabulario_vNNN.json
docker compose run --rm ingesta ingesta campana --portal bumeran --limite 20   # también: computrabajo, ambos
docker compose run --rm ingesta ingesta estado        # última ejecución y conteos
docker compose run --rm ingesta ingesta candidatos listar
docker compose run --rm ingesta ingesta candidatos aprobar <id> --termino "Kubernetes"
docker compose run --rm ingesta ingesta candidatos aprobar <id> --nuevo "MLOps" --categoria "Inteligencia Artificial"
docker compose run --rm ingesta ingesta reproceso     # aplica el vocabulario vigente al crudo, sin red
docker compose run --rm ingesta ingesta muestra --n 20   # dataset de muestra (descripción recortada)
docker compose stop                                   # detener sin perder datos
```

La campaña devuelve código 0 si la corrida es exitosa, 1 si es fallida, 2 si no se inició (día o portal) y 3 si ya hay otra corrida en curso. Cada corrida deja su documento en `ejecuciones` y su archivo en `logs/`.

## Desarrollo

- **Con VS Code:** «Dev Containers: Reopen in Container». El código se edita en el host y se ve en `/app`; el entorno de Python está en `/opt/venv`.
- **Añadir una dependencia:** `docker compose run --rm --no-deps ingesta uv add <paquete>` y después `docker compose build ingesta`.
- **Calidad:** `pre-commit` corre `ruff` y bloquea `.env` y los datos del corpus antes de cada commit. Instalación en el host: `pip install --user pre-commit` y luego `pre-commit install`.

## Pruebas

```powershell
docker compose run --rm ingesta pytest                    # unitarias + integración
docker compose run --rm ingesta pytest -m integracion     # solo las que usan MongoDB y TEI
docker compose run --rm ingesta pytest -m en_vivo         # contra los portales: solo en campaña
```

Las pruebas de integración escriben en la base `ingesta_pruebas`, nunca en `ingesta`.

## Respaldos

Los volúmenes de Docker no están dentro de `tesis_2`: si se formatea la PC o se reinstala Docker Desktop, se pierden. La evidencia de cada campaña (colección `ejecuciones`) y el corpus crudo solo existen ahí, así que se respaldan después de cada campaña en `respaldos/` (ignorada por git):

```powershell
docker compose stop mongo
docker run --rm -v ingesta_mongo_datos:/datos:ro -v "${PWD}\respaldos:/respaldo" alpine:3.22 tar czf /respaldo/mongo-AAAA-MM-DD.tgz -C /datos .
docker compose start mongo
```

Para restaurar, con `mongo` detenido y el volumen vacío: `docker run --rm -v ingesta_mongo_datos:/datos -v "${PWD}\respaldos:/respaldo" alpine:3.22 tar xzf /respaldo/<archivo>.tgz -C /datos`.

## Estructura

| Carpeta | Contenido |
|---|---|
| `config/` | `parametros.toml`: esperas, cortes, umbrales, deduplicación y regla de nivel |
| `esquemas/` | `oferta_laboral.schema.json`, copiado de R 1.4 §4 |
| `vocabulario/` | Exportador xlsx → JSON versionado y versiones del vocabulario |
| `src/ingesta/` | Un módulo por componente de la tabla del §5 del Anexo J |
| `pruebas/` | Casos del plan de pruebas funcionales |
| `docs/` | Plan de pruebas funcionales |
| `infra/` | Inicialización de MongoDB |
