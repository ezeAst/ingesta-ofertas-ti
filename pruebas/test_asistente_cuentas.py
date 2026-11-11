"""Asistente (R 3.4): cuentas, conversaciones y ofertas guardadas, con MongoDB de pruebas."""

from datetime import UTC, datetime

import pytest

from ingesta.asistente.cuentas import Cuentas, ErrorCuenta, verificar_clave
from ingesta.asistente.historial import Historial, titulo_de
from ingesta.asistente.servicio import Busqueda, Turno
from ingesta.conocimiento.busqueda import OfertaEncontrada

OFERTA = OfertaEncontrada(
    "Bumeran",
    "1",
    "Dev Java",
    "ACME",
    "https://x/1",
    datetime(2026, 10, 1, tzinfo=UTC),
    0.9,
    "frag",
    ["Java"],
)


def test_registro_y_autenticacion(bd):
    cuentas = Cuentas(bd)
    cuenta = cuentas.registrar("  Ana.Perez ", "clave-segura")
    guardado = bd.usuarios.find_one({"_id": cuenta["_id"]})
    assert guardado["usuario"] == "ana.perez" and "clave-segura" not in guardado["clave"]
    assert verificar_clave("clave-segura", guardado["clave"])
    assert cuentas.autenticar("ANA.PEREZ", "clave-segura")["_id"] == cuenta["_id"]
    assert cuentas.autenticar("ana.perez", "otra-clave") is None
    assert cuentas.autenticar("nadie", "clave-segura") is None


@pytest.mark.parametrize(
    ("usuario", "clave", "mensaje"),
    [
        ("ab", "clave-segura", "3 a 30"),
        ("josé", "clave-segura", "3 a 30"),
        ("valido", "corta", "8 caracteres"),
    ],
)
def test_registro_rechaza_datos_invalidos(bd, usuario, clave, mensaje):
    with pytest.raises(ErrorCuenta, match=mensaje):
        Cuentas(bd).registrar(usuario, clave)


def test_usuario_duplicado(bd):
    cuentas = Cuentas(bd)
    cuentas.registrar("ana", "clave-segura")
    with pytest.raises(ErrorCuenta, match="ya existe"):
        cuentas.registrar("ANA", "otra-clave-1")


def test_hash_con_sal_distinta(bd):
    cuentas = Cuentas(bd)
    a, b = cuentas.registrar("uno", "misma-clave"), cuentas.registrar("dos", "misma-clave")
    assert (
        bd.usuarios.find_one({"_id": a["_id"]})["clave"]
        != bd.usuarios.find_one({"_id": b["_id"]})["clave"]
    )


def _turno() -> Turno:
    b = Busqueda("java", {}, [OFERTA], [("Java", 1)], False)
    return Turno(
        "¿Qué piden para Java?", "buscar", texto="Piden {{Java}} [1].", busqueda=b, citas=[1]
    )


def test_conversacion_se_reabre_igual(bd):
    h = Historial(bd)
    cid = h.crear("u1", "¿Qué piden para Java?")
    h.guardar_turno("u1", cid, _turno())
    h.guardar_turno("u1", cid, Turno("gracias", "directa", texto="¡De nada!"))
    turnos = h.turnos("u1", cid)
    assert [t.tipo for t in turnos] == ["buscar", "directa"]
    assert turnos[0].busqueda.ofertas == [OFERTA] and turnos[0].texto == "Piden {{Java}} [1]."
    assert h.listar("u1")[0]["titulo"] == "¿Qué piden para Java?"


def test_aislamiento_entre_usuarios(bd):
    h = Historial(bd)
    cid = h.crear("u1", "pregunta privada")
    h.guardar_turno("u1", cid, _turno())
    assert h.listar("u2") == [] and h.turnos("u2", cid) == []
    with pytest.raises(PermissionError):
        h.guardar_turno("u2", cid, _turno())
    assert not h.borrar("u2", cid) and h.listar("u1")
    assert h.borrar("u1", cid) and bd.turnos.count_documents({}) == 0


def test_ofertas_guardadas_sin_duplicar(bd):
    h = Historial(bd)
    h.guardar_oferta("u1", OFERTA)
    h.guardar_oferta("u1", OFERTA)
    assert h.claves_guardadas("u1") == {("Bumeran", "1")} and h.claves_guardadas("u2") == set()
    assert h.ofertas_guardadas("u1")[0]["titulo"] == "Dev Java"
    h.quitar_oferta("u1", "Bumeran", "1")
    assert h.ofertas_guardadas("u1") == []


def test_titulo_recortado():
    assert titulo_de("  hola   mundo ") == "hola mundo"
    assert len(titulo_de("x" * 200)) == 60 and titulo_de("x" * 200).endswith("…")
