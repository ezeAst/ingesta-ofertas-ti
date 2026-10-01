"""El interruptor del panel cambia el parámetro sin perder los comentarios del archivo."""

import shutil

from ingesta.config import RUTA_PARAMETROS, cargar_parametros
from ingesta.panel.datos import fijar_via_semantica


def test_fijar_via_semantica_conserva_comentarios(tmp_path):
    copia = tmp_path / "parametros.toml"
    shutil.copy(RUTA_PARAMETROS, copia)
    comentarios = [
        linea for linea in copia.read_text(encoding="utf-8").splitlines() if linea.startswith("#")
    ]
    fijar_via_semantica(copia, False)
    assert cargar_parametros(copia).extraccion.usar_via_semantica is False
    fijar_via_semantica(copia, True)
    assert cargar_parametros(copia).extraccion.usar_via_semantica is True
    despues = [
        linea for linea in copia.read_text(encoding="utf-8").splitlines() if linea.startswith("#")
    ]
    assert despues == comentarios
