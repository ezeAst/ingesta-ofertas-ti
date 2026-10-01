"""CP-08 (parte unitaria): los datos de contacto se eliminan antes de guardar el crudo."""

from ingesta.privacidad import MARCA, eliminar_contactos, limpiar_estructura


def test_elimina_correo_y_celular_de_persona_natural():
    texto = "Enviar CV a maria.perez@empresa.com.pe o al 987 654 321 hasta el lunes."
    limpio, n = eliminar_contactos(texto)
    assert "maria.perez" not in limpio
    assert "987" not in limpio
    assert limpio.count(MARCA) == 2
    assert n == 2


def test_elimina_celular_con_prefijo_de_pais_y_fijo_de_lima():
    limpio, n = eliminar_contactos("Llamar al +51 912-345-678 o al (01) 234-5678.")
    assert "912" not in limpio
    assert "234-5678" not in limpio
    assert n == 2


def test_no_toca_montos_ruc_ni_anios():
    texto = "Sueldo S/ 3500, RUC 20512345678, experiencia desde 2019, 3 vacantes."
    limpio, n = eliminar_contactos(texto)
    assert limpio == texto
    assert n == 0


def test_limpia_recursivamente_un_documento_json():
    doc = {
        "titulo": "Analista",
        "detalle": "Escribir a rrhh.juan@correo.com",
        "otros": [{"nota": "cel 999888777"}, 5, None],
    }
    limpio, n = limpiar_estructura(doc)
    assert "rrhh.juan" not in limpio["detalle"]
    assert "999888777" not in limpio["otros"][0]["nota"]
    assert limpio["otros"][1:] == [5, None]
    assert n == 2
    assert doc["detalle"] == "Escribir a rrhh.juan@correo.com"  # no muta el original
