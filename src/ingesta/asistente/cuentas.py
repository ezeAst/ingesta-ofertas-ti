"""Cuentas del asistente: usuario y contraseña, sin correo ni datos personales (Ley N° 29733).

La contraseña se guarda con scrypt (biblioteca estándar) y sal aleatoria; nunca en claro.
"""

import hashlib
import hmac
import os
import re
from datetime import UTC, datetime

from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

_PATRON_USUARIO = re.compile(r"^[a-z0-9_.-]{3,30}$")
_N, _R, _P = 2**14, 8, 1  # parámetros de scrypt (≈16 MB de memoria por verificación)
MINIMO_CLAVE = 8


class ErrorCuenta(ValueError):
    """Mensaje pensado para mostrarse tal cual al usuario."""


def hash_clave(clave: str) -> str:
    sal = os.urandom(16)
    h = hashlib.scrypt(clave.encode(), salt=sal, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${sal.hex()}${h.hex()}"


def verificar_clave(clave: str, guardado: str) -> bool:
    try:
        _, n, r, p, sal, h = guardado.split("$")
        calculado = hashlib.scrypt(
            clave.encode(), salt=bytes.fromhex(sal), n=int(n), r=int(r), p=int(p), dklen=32
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calculado.hex(), h)


def normalizar_usuario(usuario: str) -> str:
    return usuario.strip().lower()


class Cuentas:
    def __init__(self, bd: Database):
        self._usuarios = bd.usuarios

    def registrar(self, usuario: str, clave: str) -> dict:
        usuario = normalizar_usuario(usuario)
        if not _PATRON_USUARIO.match(usuario):
            raise ErrorCuenta(
                "El usuario debe tener de 3 a 30 caracteres: letras sin tilde, números, punto, guion o guion bajo."
            )
        if len(clave) < MINIMO_CLAVE:
            raise ErrorCuenta(f"La contraseña debe tener al menos {MINIMO_CLAVE} caracteres.")
        documento = {"usuario": usuario, "clave": hash_clave(clave), "creado": datetime.now(UTC)}
        try:
            resultado = self._usuarios.insert_one(documento)
        except DuplicateKeyError:
            raise ErrorCuenta("Ese usuario ya existe. Elige otro o inicia sesión.") from None
        return {"_id": resultado.inserted_id, "usuario": usuario}

    def autenticar(self, usuario: str, clave: str) -> dict | None:
        documento = self._usuarios.find_one({"usuario": normalizar_usuario(usuario)})
        if documento is None or not verificar_clave(clave, documento["clave"]):
            return None
        return {"_id": documento["_id"], "usuario": documento["usuario"]}
