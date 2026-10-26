"""BC-01 a BC-04: textos que se vectorizan por oferta (R 2.4, V2, V3 y V10)."""

import uuid
from itertools import pairwise

from ingesta.conocimiento.textos import (
    fragmentar,
    huella,
    id_punto,
    texto_competencias,
    texto_titulo,
)

from .utiles import EmbebedorPalabras

PREFIJO = "passage: "
contar = EmbebedorPalabras().contar_tokens


def oferta(descripcion="Requisitos: Python y SQL.", nombres=("Python", "SQL"), **extra):
    return {
        "titulo": "Analista",
        "descripcion": descripcion,
        "fuente": {"portal": "Computrabajo", "id_aviso": "A1", "fecha_extraccion": "2026-10-01"},
        "competencias": [
            {"nombre": n, "categoria": "Lenguajes de programación", "tipo": "técnica"}
            for n in nombres
        ],
        **extra,
    }


def test_bc01_id_punto_es_estable_y_distingue_portal():
    assert id_punto("Bumeran", "1") == id_punto("Bumeran", "1")
    assert id_punto("Bumeran", "1") != id_punto("Computrabajo", "1")
    uuid.UUID(id_punto("Bumeran", "1"))


def test_bc02_huella_cambia_si_cambian_las_competencias():
    assert huella(oferta()) != huella(oferta(nombres=("Python", "Java")))


def test_bc02_huella_no_depende_de_otros_campos():
    otra = oferta()
    otra["fuente"] = {**otra["fuente"], "fecha_extraccion": "2026-10-20"}
    assert huella(oferta()) == huella(otra)


def test_bc03_textos_de_titulo_y_competencias():
    assert texto_titulo(oferta(), PREFIJO) == "passage: Analista"
    assert (
        texto_competencias(oferta(nombres=("Python", "SQL", "Python")), PREFIJO)
        == "passage: Analista. Competencias: Python, SQL"
    )


def test_bc04_fragmentar_excluye_beneficios():
    o = oferta("Requisitos: Python y SQL. ¿Qué ofrecemos? Bono de alimentación")
    fragmentos = fragmentar(o, PREFIJO, 400, contar)
    assert fragmentos
    assert all(f.startswith("passage: Analista — ") for f in fragmentos)
    assert not any("Bono" in f for f in fragmentos)


def test_bc04_fragmentar_parte_por_tamano_con_solapamiento():
    frases = [f"Frase {i} con nueve palabras para medir el largo." for i in range(30)]
    fragmentos = fragmentar(oferta("\n".join(frases)), PREFIJO, 60, contar)
    assert len(fragmentos) > 1
    assert all(contar([f])[0] <= 60 for f in fragmentos)
    for anterior, siguiente in pairwise(fragmentos):
        ultima = anterior.split(" — ", 1)[1].split(". ")[-1]
        assert siguiente.split(" — ", 1)[1].startswith(ultima)
    assert "Frase 29" in fragmentos[-1]


def test_bc04_fragmentar_sin_unidades_devuelve_el_titulo():
    o = oferta("¿Qué ofrecemos?\nBono de alimentación y seguro.")
    assert fragmentar(o, PREFIJO, 400, contar) == ["passage: Analista"]


def test_bc04_unidad_larga_va_sola():
    larga = " ".join(["palabra"] * 100) + "."
    o = oferta(f"Requisitos: Python.\n{larga}\nTrabajo en equipo.")
    fragmentos = fragmentar(o, PREFIJO, 60, contar)
    assert sum(1 for f in fragmentos if larga in f) == 1
    assert any(f.endswith(larga) and "Python" not in f for f in fragmentos)
