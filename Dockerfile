# syntax=docker/dockerfile:1.7
# Imagen de la aplicación de ingesta (R 2.3) y de carga de la base de conocimiento (R 2.4).
# Sigue la guía oficial de uv para Docker: versión de uv fijada, capa de dependencias
# separada del código, caché de uv montada y bytecode precompilado.
# El modelo de embeddings NO vive aquí: lo sirve el contenedor `embeddings` (TEI) con la GPU.

FROM python:3.13.15-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    TZ=America/Lima

# Usuario sin privilegios. El entorno virtual vive fuera de /app para que montar
# el código fuente durante el desarrollo no lo pise.
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home app \
    && install -d -o app -g app /opt/venv /app

USER app
WORKDIR /app

# 1) Dependencias: solo se reconstruye esta capa cuando cambian pyproject.toml o uv.lock.
RUN --mount=type=cache,target=/home/app/.cache/uv,uid=1000,gid=1000 \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

# 2) Código del proyecto.
COPY --chown=app:app . /app
RUN --mount=type=cache,target=/home/app/.cache/uv,uid=1000,gid=1000 \
    uv sync --locked

CMD ["python", "-c", "import ingesta; print(ingesta.__doc__)"]
