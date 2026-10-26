"""Línea de comandos: el punto de entrada que usa el tesista."""

import pytest
from typer.testing import CliRunner

from ingesta.cli import app

from .conftest import XLSX_VOCABULARIO
from .test_vocabulario import requiere_xlsx

runner = CliRunner()


def test_la_ayuda_lista_los_comandos():
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    for comando in (
        "preparar",
        "campana",
        "reproceso",
        "vocabulario",
        "candidatos",
        "muestra",
        "estado",
    ):
        assert comando in r.output


@requiere_xlsx
def test_exportar_vocabulario_crea_la_version_1(tmp_path):
    r = runner.invoke(
        app,
        ["vocabulario", "exportar", "--xlsx", str(XLSX_VOCABULARIO), "--carpeta", str(tmp_path)],
    )
    assert r.exit_code == 0, r.output
    assert (tmp_path / "vocabulario_v001.json").exists()
    assert "322 términos" in r.output


def test_bc18_la_ayuda_lista_vectorizar_y_buscar():
    r = runner.invoke(app, ["--help"])
    assert "vectorizar" in r.output
    assert "buscar" in r.output


@pytest.mark.integracion
def test_bc18_vectorizar_se_niega_con_corrida_en_curso(bd, monkeypatch):
    import os
    import socket
    from datetime import UTC, datetime

    monkeypatch.setenv("MONGO_BD", bd.name)
    bd.ejecuciones.insert_one(
        {
            "modo": "campana",
            "estado": "en_curso",
            "inicio": datetime.now(UTC),
            "pid": os.getpid(),
            "host": socket.gethostname(),
        }
    )
    r = runner.invoke(app, ["vectorizar"])
    assert r.exit_code == 3
    assert "en curso" in r.output


@pytest.mark.integracion
def test_estado_ignora_las_vectorizaciones(bd, monkeypatch):
    from datetime import UTC, datetime

    monkeypatch.setenv("MONGO_BD", bd.name)
    bd.ejecuciones.insert_one(
        {
            "modo": "vectorizacion",
            "estado": "exitosa",
            "inicio": datetime.now(UTC),
            "resultados": {},
        }
    )
    r = runner.invoke(app, ["estado"])
    assert r.exit_code == 0, r.output


def test_bc23_el_resumen_muestra_el_estado_de_la_base(capsys):
    from ingesta.cli import _resumen

    _resumen(
        {
            "estado": "exitosa",
            "duracion_s": 1.0,
            "resultados": {"publicados": 1, "descartes": {}, "candidatos_encolados": 0},
            "archivo_registro": "x.log",
            "base_conocimiento": {"estado": "desactualizada", "error": "sin conexión"},
        }
    )
    salida = capsys.readouterr().out
    assert "Base de conocimiento: desactualizada" in salida
    assert "ingesta vectorizar" in salida
