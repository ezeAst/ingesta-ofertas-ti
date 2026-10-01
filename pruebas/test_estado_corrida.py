"""CP-36: criterio de corrida fallida (Anexo J §9)."""

from ingesta.registro import estado_corrida, tasa_exito


def test_tasa_de_exito_por_fuente():
    assert tasa_exito(obtenidos=49, fallidos=51) == 0.49
    assert tasa_exito(obtenidos=0, fallidos=0) == 1.0  # nada nuevo que pedir no es un fallo


def test_cp36_frontera_del_cincuenta_por_ciento():
    estado, motivos = estado_corrida(
        {"Bumeran": 0.49, "Computrabajo": 1.0}, robots_permitido=True, minimo=0.5
    )
    assert estado == "fallida" and motivos == ["Bumeran: tasa de éxito 49 % < 50 %"]
    estado, motivos = estado_corrida(
        {"Bumeran": 0.50, "Computrabajo": 1.0}, robots_permitido=True, minimo=0.5
    )
    assert estado == "exitosa" and motivos == []


def test_robots_prohibido_marca_la_corrida_como_fallida():
    estado, motivos = estado_corrida({}, robots_permitido=False, minimo=0.5)
    assert estado == "fallida" and "robots.txt" in motivos[0]
