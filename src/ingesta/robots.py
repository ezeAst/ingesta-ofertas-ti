"""Verificador de robots.txt (compromiso 1 de R 2.1).

Se relee antes de cada campaña. Si alguna ruta vigilada queda prohibida, o el archivo no se
puede leer, la campaña no arranca. Un cambio fuera de esas rutas solo se registra.
"""

import hashlib
from dataclasses import dataclass
from urllib.robotparser import RobotFileParser

from ingesta.cliente_http import ClienteHTTP


@dataclass(frozen=True)
class ResultadoRobots:
    url: str
    permitido: bool
    prohibidas: list[str]
    texto: str
    huella: str
    cambio: bool


def verificar_robots(
    cliente: ClienteHTTP,
    url_robots: str,
    rutas: list[str],
    user_agent: str,
    huella_anterior: str | None,
) -> ResultadoRobots:
    respuesta = cliente.get(url_robots)
    if respuesta is None:
        return ResultadoRobots(url_robots, False, list(rutas), "", "", False)
    texto = respuesta.text
    huella = hashlib.sha256(texto.encode()).hexdigest()
    lector = RobotFileParser()
    lector.parse(texto.splitlines())
    base = url_robots.removesuffix("/robots.txt")
    prohibidas = [r for r in rutas if not lector.can_fetch(user_agent, base + r)]
    cambio = huella_anterior is not None and huella != huella_anterior
    return ResultadoRobots(url_robots, not prohibidas, prohibidas, texto, huella, cambio)
