"""Dataset de muestra para la tesis (medio de verificación de R 2.3).

El corpus en bruto no se redistribuye (compromiso 7): la muestra sale de `ofertas_laborales`,
sin identificadores internos y con la descripción recortada.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from pymongo.database import Database


def exportar_muestra(bd: Database, n: int, carpeta: Path, max_caracteres: int = 300) -> Path:
    ofertas = list(
        bd.ofertas_laborales.aggregate([{"$sample": {"size": n}}, {"$project": {"_id": 0}}])
    )
    for oferta in ofertas:
        texto = oferta["descripcion"]
        if len(texto) > max_caracteres:
            oferta["descripcion"] = texto[:max_caracteres].rstrip() + "…"
    ahora = datetime.now(UTC)
    salida = {
        "generado": ahora.isoformat(timespec="seconds"),
        "total_en_base": bd.ofertas_laborales.count_documents({}),
        "nota": (
            f"Descripción recortada a {max_caracteres} caracteres; "
            "el corpus en bruto no se redistribuye."
        ),
        "ofertas": ofertas,
    }
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"muestra_{ahora:%Y-%m-%d_%H%M}.json"
    ruta.write_text(
        json.dumps(salida, ensure_ascii=False, indent=1, default=_fecha) + "\n", encoding="utf-8"
    )
    return ruta


def _fecha(valor):
    if isinstance(valor, datetime):
        return valor.isoformat()
    raise TypeError(f"no serializable: {type(valor).__name__}")
