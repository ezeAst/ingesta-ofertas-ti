"""Línea de comandos: el punto de entrada que usa el tesista."""

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
