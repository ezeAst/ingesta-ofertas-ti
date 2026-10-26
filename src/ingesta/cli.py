"""Línea de comandos: `docker compose run --rm ingesta ingesta <comando>`."""

from pathlib import Path
from typing import Annotated

import typer

from ingesta.config import (
    DIR_EXPORTACIONES,
    DIR_VOCABULARIO,
    Entorno,
)

app = typer.Typer(
    help="Mecanismo de ingesta de ofertas laborales de TI (R 2.3) y base de conocimiento (R 2.4).",
    no_args_is_help=True,
)
vocabulario_app = typer.Typer(help="Vocabulario controlado de R 1.3.", no_args_is_help=True)
candidatos_app = typer.Typer(help="Cola de candidatos para revisión humana.", no_args_is_help=True)
app.add_typer(vocabulario_app, name="vocabulario")
app.add_typer(candidatos_app, name="candidatos")


def _bd():
    from ingesta.servicios import conectar_bd

    return conectar_bd()


def _dependencias(bd):
    from ingesta.servicios import construir_dependencias

    return construir_dependencias(bd)


def _sin_corrida_en_curso(bd) -> None:
    from ingesta.gestion import corrida_en_curso

    if (otra := corrida_en_curso(bd)) is not None:
        typer.echo(
            f"Ya hay una corrida en curso ({otra['modo']}, pid {otra.get('pid')}).", err=True
        )
        raise typer.Exit(3)


def _resumen(ejecucion: dict) -> None:
    typer.echo(f"Estado: {ejecucion['estado']}  ({ejecucion['duracion_s']} s)")
    for motivo in ejecucion.get("motivos", []):
        typer.echo(f"  - {motivo}")
    for nombre, f in ejecucion.get("fuentes", {}).items():
        typer.echo(
            f"{nombre}: vistos {f['vistos']}, nuevos {f['nuevos']}, fallidos {f['fallidos']}, "
            f"tasa de éxito {f['tasa_exito']:.0%}"
        )
    r = ejecucion["resultados"]
    typer.echo(
        f"Publicados: {r['publicados']} | descartes: {r['descartes']} | "
        f"candidatos nuevos: {r['candidatos_encolados']}"
    )
    typer.echo(f"Registro: {ejecucion['archivo_registro']}")
    if base := ejecucion.get("base_conocimiento"):
        typer.echo(f"Base de conocimiento: {base['estado']}")
        if base["estado"] == "desactualizada":
            typer.echo(
                f"  {base.get('error')}. Ejecuta `ingesta vectorizar` cuando Qdrant responda."
            )


@app.command()
def preparar() -> None:
    """Crea las colecciones, el validador de R 1.4 y los índices (se puede repetir)."""
    bd = _bd()
    typer.echo(f"Base «{bd.name}» lista: {', '.join(sorted(bd.list_collection_names()))}")


@app.command()
def campana(
    portal: Annotated[
        str, typer.Option(help="bumeran, computrabajo o ambos.", case_sensitive=False)
    ] = "ambos",
    limite: Annotated[
        int | None, typer.Option(help="Máximo de avisos nuevos por portal (corrida de prueba).")
    ] = None,
) -> None:
    """Campaña: robots.txt, portal(es) elegido(s) y procesamiento de los avisos nuevos."""
    from ingesta.campana import PORTALES, CampanaFueraDeDia, ejecutar_campana

    portales = (
        list(PORTALES)
        if portal.lower() == "ambos"
        else [p for p in PORTALES if p.lower() == portal.lower()]
    )
    if not portales:
        typer.echo(f"Portal desconocido: {portal}.", err=True)
        raise typer.Exit(2)
    bd = _bd()
    _sin_corrida_en_curso(bd)
    try:
        ejecucion = ejecutar_campana(_dependencias(bd), portales=portales, limite=limite)
    except CampanaFueraDeDia as error:
        typer.echo(f"No se inicia: {error}.", err=True)
        raise typer.Exit(2) from error
    _resumen(ejecucion)
    raise typer.Exit(0 if ejecucion["estado"] == "exitosa" else 1)


@app.command()
def reproceso() -> None:
    """Reprocesa todo el crudo con el vocabulario vigente, sin consultar los portales."""
    from ingesta.campana import ejecutar_reproceso

    bd = _bd()
    _sin_corrida_en_curso(bd)
    _resumen(ejecutar_reproceso(_dependencias(bd)))


@app.command()
def muestra(
    n: Annotated[int, typer.Option(help="Cantidad de ofertas.")] = 20,
    caracteres: Annotated[int, typer.Option(help="Largo máximo de la descripción.")] = 300,
) -> None:
    """Exporta el dataset de muestra a exportaciones/ (descripción recortada)."""
    from ingesta.muestra import exportar_muestra

    typer.echo(f"Muestra: {exportar_muestra(_bd(), n, DIR_EXPORTACIONES, caracteres)}")


@app.command()
def estado() -> None:
    """Resumen de la última campaña o reproceso y de las colecciones."""
    bd = _bd()
    ultima = bd.ejecuciones.find_one({"modo": {"$ne": "vectorizacion"}}, sort=[("inicio", -1)])
    if ultima is None:
        typer.echo("Todavía no hay ejecuciones.")
    elif "resultados" in ultima:
        typer.echo(f"Última ejecución: {ultima['modo']} del {ultima['inicio']:%Y-%m-%d %H:%M} UTC")
        _resumen(ultima)
    for nombre in (
        "avisos_crudos",
        "ofertas_laborales",
        "ofertas_descartadas",
        "candidatos_competencia",
    ):
        typer.echo(f"{nombre}: {bd[nombre].count_documents({})}")


@app.command()
def vectorizar(
    todo: Annotated[
        bool, typer.Option(help="Borra la colección de Qdrant y la reconstruye desde cero.")
    ] = False,
) -> None:
    """Sincroniza ofertas_laborales con Qdrant (R 2.4); también corre al final de cada campaña."""
    from ingesta.conocimiento.vectorizacion import ejecutar_vectorizacion

    bd = _bd()
    _sin_corrida_en_curso(bd)
    e = ejecutar_vectorizacion(_dependencias(bd), todo=todo)
    r = e["resultados"]
    typer.echo(
        f"Qdrant «{e['coleccion']}»: {r['creadas']} creadas, {r['actualizadas']} actualizadas, "
        f"{r['borradas']} borradas, {r['sin_cambios']} sin cambios ({e['duracion_s']} s)"
    )
    typer.echo(
        f"Puntos: {r['puntos']} | fragmentos cargados: {r['fragmentos']} "
        f"(recortados por el modelo: {r['fragmentos_recortados']}) | por portal: {r['por_portal']}"
    )


@app.command()
def buscar(
    consulta: str,
    via: Annotated[
        str | None, typer.Option(help="Un solo vector: titulo, competencias o fragmentos.")
    ] = None,
    competencia: Annotated[
        list[str] | None, typer.Option(help="Exige esta competencia (repetible).")
    ] = None,
    categoria: Annotated[list[str] | None, typer.Option(help="Categoría de R 1.2.")] = None,
    portal: Annotated[list[str] | None, typer.Option(help="Bumeran o Computrabajo.")] = None,
) -> None:
    """Prueba la búsqueda de la base de conocimiento, sin LLM (R 2.4)."""
    from ingesta.config import cargar_parametros
    from ingesta.conocimiento.busqueda import Filtros
    from ingesta.conocimiento.busqueda import buscar as buscar_ofertas
    from ingesta.embeddings import ClienteTEI
    from ingesta.servicios import conectar_qdrant

    filtros = Filtros(
        competencias=tuple(competencia or ()),
        categorias=tuple(categoria or ()),
        portales=tuple(portal or ()),
    )
    try:
        r = buscar_ofertas(
            _bd(),
            conectar_qdrant(),
            ClienteTEI(Entorno().embeddings_url),
            cargar_parametros().base_conocimiento,
            consulta,
            filtros,
            via,
        )
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    filtradas = "" if r.filtradas is None else f", {r.filtradas} tras los filtros"
    typer.echo(f"{len(r.ofertas)} ofertas (vía {r.via}{filtradas})")
    for o in r.ofertas:
        typer.echo(f"  {o.puntaje:.3f}  {o.portal:<12} {o.titulo} · {o.empresa}")
    typer.echo("Competencias más pedidas:")
    for nombre, n in r.conteo[:15]:
        typer.echo(f"  {n:>3}  {nombre}")
    if not r.suficiente:
        typer.echo("Aviso: poca evidencia (menos ofertas que el mínimo configurado).")


@vocabulario_app.command("exportar")
def vocabulario_exportar(
    xlsx: Annotated[Path | None, typer.Option(help="xlsx de R 1.3.")] = None,
    carpeta: Annotated[Path, typer.Option(help="Carpeta de versiones.")] = DIR_VOCABULARIO,
) -> None:
    """Exporta el xlsx de R 1.3 a una versión nueva, solo si el contenido cambió."""
    from ingesta.vocabulario import Vocabulario, exportar_desde_xlsx, guardar_version

    datos = exportar_desde_xlsx(xlsx or Entorno().vocabulario_xlsx)
    ruta = guardar_version(datos, carpeta)
    vocab = Vocabulario.cargar_vigente(carpeta)
    literales = sum(len(t["literales"]) for t in vocab.terminos)
    descriptivas = sum(len(t["descriptivas"]) for t in vocab.terminos)
    typer.echo(
        f"{ruta.name}: {len(vocab.terminos)} términos, "
        f"{len(vocab.datos['categorias'])} categorías, "
        f"{literales} variantes literales y {descriptivas} descriptivas"
    )


@candidatos_app.command("listar")
def candidatos_listar(limite: Annotated[int, typer.Option(help="Máximo a mostrar.")] = 50) -> None:
    """Candidatos pendientes: por embeddings (del puntaje más alto al más bajo) y por descarte
    (del tramo más mencionado al menos mencionado)."""
    from ingesta.config import cargar_parametros
    from ingesta.panel.datos import candidatos_embedding, candidatos_lexicos

    bd = _bd()
    typer.echo("Por embeddings:")
    for c in candidatos_embedding(bd)[:limite]:
        typer.echo(
            f"{c['_id']}  {c['puntaje']:.3f}  «{c['tramo']}» → {c['termino_cercano']}  "
            f"({c['portal']} {c['id_aviso']})"
        )
    minimo = cargar_parametros().extraccion.via_lexica.min_avisos
    typer.echo(f"Por descarte (mencionados en {minimo} avisos o más):")
    for c in candidatos_lexicos(bd, minimo)[:limite]:
        typer.echo(f"{c['_id']}  {c['n_avisos']} avisos  «{c['tramo']}»")


@candidatos_app.command("aprobar")
def candidatos_aprobar(
    id_candidato: str,
    termino: Annotated[
        str | None, typer.Option(help="Término existente al que se añade la variante.")
    ] = None,
    nuevo: Annotated[str | None, typer.Option(help="Nombre de un término canónico nuevo.")] = None,
    categoria: Annotated[
        str | None, typer.Option(help="Categoría de R 1.2 del término nuevo.")
    ] = None,
    descriptiva: Annotated[bool, typer.Option(help="Añadir como variante descriptiva.")] = False,
) -> None:
    """Aprueba un candidato y crea una versión nueva del vocabulario.

    Después hay que ejecutar `ingesta reproceso` para aplicarla.
    """
    from ingesta.candidatos import aprobar

    ruta = aprobar(
        _bd(),
        id_candidato,
        DIR_VOCABULARIO,
        termino=termino,
        nuevo_termino=nuevo,
        categoria=categoria,
        descriptiva=descriptiva,
    )
    typer.echo(f"Vocabulario actualizado: {ruta.name}. Ejecuta `ingesta reproceso` para aplicarlo.")


@candidatos_app.command("rechazar")
def candidatos_rechazar(id_candidato: str) -> None:
    """Rechaza un candidato; no vuelve a encolarse."""
    from ingesta.candidatos import rechazar

    rechazar(_bd(), id_candidato)
    typer.echo("Candidato rechazado.")
