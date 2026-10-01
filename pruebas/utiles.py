"""Dobles de prueba y datos sintéticos."""

import re
import zlib

import numpy as np

from ingesta.vocabulario import Vocabulario

DIM = 512


class EmbebedorPalabras:
    """Embebedor falso: bolsa de palabras con hashing. La similitud coseno es alta solo si
    los textos comparten palabras, así que las pruebas son predecibles sin la GPU."""

    def __init__(self):
        self.llamadas: list[list[str]] = []

    def vectorizar(self, textos: list[str]) -> np.ndarray:
        self.llamadas.append(list(textos))
        matriz = np.zeros((len(textos), DIM))
        for i, texto in enumerate(textos):
            texto = texto.removeprefix("query: ").removeprefix("passage: ")
            for palabra in re.findall(r"\w+", texto.lower()):
                matriz[i, zlib.crc32(palabra.encode()) % DIM] += 1.0
            norma = np.linalg.norm(matriz[i])
            if norma:
                matriz[i] /= norma
        return matriz


def _t(nombre, categoria, literales=(), descriptivas=()):
    return {
        "nombre": nombre,
        "categoria": categoria,
        "literales": list(literales),
        "descriptivas": list(descriptivas),
    }


VOCAB_PRUEBA = {
    "version": 1,
    "categorias": {
        "Lenguajes de programación": "técnica",
        "Bases de datos": "técnica",
        "Cloud, Infraestructura y Operaciones": "técnica",
        "Control de versiones y CI/CD": "técnica",
        "Trabajo en equipo": "transversal",
        "Comunicación": "transversal",
        "Pensamiento analítico": "transversal",
    },
    "terminos": [
        _t("SQL", "Lenguajes de programación"),
        _t("SQL Server", "Bases de datos"),
        _t("Java", "Lenguajes de programación"),
        _t("JavaScript", "Lenguajes de programación", ["JS"]),
        _t("Python", "Lenguajes de programación", ["Phyton", "Python 3"]),
        _t("R", "Lenguajes de programación"),
        _t("Go", "Lenguajes de programación", ["Golang"]),
        _t("PostgreSQL", "Bases de datos", ["Postgres", "Postgree"]),
        _t("AWS", "Cloud, Infraestructura y Operaciones", ["Amazon Web Services", "EKS"]),
        _t(
            "Kubernetes",
            "Cloud, Infraestructura y Operaciones",
            ["K8s", "EKS"],
            ["orquestación de contenedores"],
        ),
        _t("Docker", "Cloud, Infraestructura y Operaciones"),
        _t(
            "Alta disponibilidad",
            "Cloud, Infraestructura y Operaciones",
            ["High Availability"],
            ["backups"],
        ),
        _t(
            "Infraestructura como código",
            "Cloud, Infraestructura y Operaciones",
            ["IaC"],
            ["infraestructura declarativa versionada"],
        ),
        _t("Git", "Control de versiones y CI/CD", ["GitHub"]),
        _t("Trabajo en equipo", "Trabajo en equipo", ["trabajo colaborativo"]),
        _t("Comunicación efectiva", "Comunicación"),
        _t("Pensamiento analítico", "Pensamiento analítico"),
    ],
}


def vocab_prueba() -> Vocabulario:
    return Vocabulario(VOCAB_PRUEBA)


class RelojFalso:
    """Reloj controlado: `dormir` avanza el tiempo sin esperar de verdad."""

    def __init__(self):
        self.t = 0.0
        self.pausas: list[float] = []

    def __call__(self) -> float:
        return self.t

    def dormir(self, segundos: float) -> None:
        self.pausas.append(segundos)
        self.t += segundos


def item_bumeran(id_aviso: int, titulo: str = "Analista Programador", **extra) -> dict:
    """Aviso con la forma que devuelve POST /api/avisos/searchV2 (sondeo del 2026-09-27)."""
    return {
        "id": id_aviso,
        "titulo": titulo,
        "detalle": "Buscamos analista.  Python y SQL  Git"
        "Conocimientos y Certificaciones Indispensables: Python  SQL",
        "empresa": "ACME S.A.C.",
        "confidencial": False,
        "fechaHoraPublicacion": "26-09-2026 00:45:10",
        "fechaPublicacion": "26-09-2026",
        "localizacion": "Surco, Lima",
        "modalidadTrabajo": "Presencial",
        **extra,
    }


def pagina_bumeran(items: list[dict], total: int, numero: int = 0, tamano: int = 20) -> dict:
    return {"number": numero, "size": tamano, "total": total, "content": items}


def listado_computrabajo(ids_y_rutas: list[tuple[str, str]]) -> str:
    articulos = "".join(
        f'<article class="box_offer" data-id="{i}">'
        f'<h2><a href="{r}#lc=ListOffers-Score4-0">x</a></h2>'
        f'<a href="https://pe.computrabajo.com/empresas/ofertas-de-trabajo-de-acme-1">ACME</a></article>'
        for i, r in ids_y_rutas
    )
    return f"<html><body>{articulos}</body></html>"


def detalle_computrabajo(
    jobposting: dict | None, visible: str = "Texto visible de la página"
) -> str:
    import json

    bloque = (
        '<script type="application/ld+json">'
        f"{json.dumps([{'@type': 'BreadcrumbList'}, jobposting])}</script>"
        if jobposting
        else ""
    )
    return f"<html><head>{bloque}</head><body><div>{visible}</div></body></html>"


def jobposting(
    titulo: str = "Desarrollador Java", descripcion: str = "Java<br>Spring Boot y SQL"
) -> dict:
    return {
        "@type": "JobPosting",
        "title": titulo,
        "description": descripcion,
        "datePosted": "2026-09-20",
        "validThrough": "2026-11-20",
        "industry": "Servicios Profesionales",
        "hiringOrganization": {"@type": "Organization", "name": "ACME S.A.C."},
    }
