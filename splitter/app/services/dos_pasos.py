"""Verificación en dos pasos con una app de autenticación (TOTP, RFC 6238).

1. iniciar(): crea un secreto nuevo (aún sin activar) y devuelve el QR para escanearlo.
2. confirmar(codigo): si el código de la app es correcto, se activa y se dan 8 códigos
   de respaldo (se muestran una sola vez; se guardan solo sus hashes).
3. Al iniciar sesión se pide el código de 6 dígitos, o uno de respaldo (sirve una vez).
"""
import base64
import hashlib
import hmac
import io
import json
import secrets
import struct
import time
from typing import List, Optional
from urllib.parse import quote

import qrcode
import qrcode.image.svg
from fastapi import HTTPException

from ..database import SessionLocal
from ..models.tablas import Usuario
from ..repositories import usuarios as repo_usuarios
from . import auth, correo

EMISOR = "Splitter"
PASO = 30  # segundos que dura cada código
DIGITOS = 6
CODIGOS_RESPALDO = 8
# Códigos ya usados (contra repetir uno robado dentro de su ventana): (usuario, contador)
_usados: dict = {}


def _codigo(secreto: str, contador: int) -> str:
    clave = base64.b32decode(secreto + "=" * (-len(secreto) % 8), casefold=True)
    digest = hmac.new(clave, struct.pack(">Q", contador), hashlib.sha1).digest()
    desde = digest[-1] & 0x0F
    numero = struct.unpack(">I", digest[desde:desde + 4])[0] & 0x7FFFFFFF
    return str(numero % 10 ** DIGITOS).zfill(DIGITOS)


def codigo_actual(secreto: str, momento: Optional[float] = None) -> str:
    return _codigo(secreto, int((momento or time.time()) // PASO))


def _totp_valido(usuario_id: int, secreto: str, codigo: str) -> bool:
    """Acepta el código de ahora y el de 30 s antes o después (relojes desfasados)."""
    contador = int(time.time() // PASO)
    for c in (contador - 1, contador, contador + 1):
        if hmac.compare_digest(_codigo(secreto, c), codigo):
            if _usados.get(usuario_id, -1) >= c:
                return False  # ya se usó este código o uno más nuevo
            _usados[usuario_id] = c
            return True
    return False


def _hash_respaldo(codigo: str) -> str:
    return hashlib.sha256(codigo.replace("-", "").lower().encode()).hexdigest()


def _limpio(codigo: str) -> str:
    return (codigo or "").strip().replace(" ", "")


def verificar(usuario: Usuario, codigo: str, db) -> bool:
    """Código de la app (6 dígitos) o uno de respaldo (xxxx-xxxx, se gasta al usarlo)."""
    codigo = _limpio(codigo)
    if not codigo or not usuario.totp_secreto:
        return False
    if codigo.isdigit() and len(codigo) == DIGITOS:
        return _totp_valido(usuario.id, usuario.totp_secreto, codigo)
    respaldo: List[str] = json.loads(usuario.totp_respaldo or "[]")
    buscado = _hash_respaldo(codigo)
    for guardado in respaldo:
        if hmac.compare_digest(guardado, buscado):
            respaldo.remove(guardado)
            usuario.totp_respaldo = json.dumps(respaldo)
            return True
    return False


def _qr_svg(texto: str) -> str:
    imagen = qrcode.make(texto, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    salida = io.BytesIO()
    imagen.save(salida)
    return "data:image/svg+xml;base64," + base64.b64encode(salida.getvalue()).decode()


def iniciar(usuario_id: int) -> dict:
    with SessionLocal() as db:
        usuario = repo_usuarios.buscar_por_id(db, usuario_id)
        if usuario.totp_activo:
            raise HTTPException(409, "Ya tienes activa la verificación en dos pasos.")
        secreto = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
        usuario.totp_secreto = secreto
        db.commit()
        enlace = (
            f"otpauth://totp/{quote(EMISOR)}:{quote(usuario.email)}"
            f"?secret={secreto}&issuer={quote(EMISOR)}&digits={DIGITOS}&period={PASO}"
        )
    return {"secreto": secreto, "enlace": enlace, "qr": _qr_svg(enlace)}


def confirmar(usuario_id: int, codigo: str) -> dict:
    with SessionLocal() as db:
        usuario = repo_usuarios.buscar_por_id(db, usuario_id)
        if usuario.totp_activo:
            raise HTTPException(409, "Ya tienes activa la verificación en dos pasos.")
        if not usuario.totp_secreto or not _limpio(codigo).isdigit() or not _totp_valido(usuario.id, usuario.totp_secreto, _limpio(codigo)):
            raise HTTPException(400, "El código no es correcto. Revisa que la hora de tu teléfono esté bien y usa el código más nuevo.")
        respaldo = [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(CODIGOS_RESPALDO)]
        usuario.totp_activo = True
        usuario.totp_respaldo = json.dumps([_hash_respaldo(c) for c in respaldo])
        db.commit()
        email, nombre = usuario.email, usuario.nombre
    correo.enviar_aviso(
        email, "Activaste la verificación en dos pasos", f"Hola, {nombre}",
        ["Desde ahora, al iniciar sesión en Splitter te pediremos el código de tu app de autenticación."],
        pie="Si no fuiste tú, cambia tu contraseña de inmediato.",
    )
    return {"activo": True, "codigos_respaldo": respaldo}


def desactivar(usuario_id: int, password: str, codigo: str) -> None:
    with SessionLocal() as db:
        usuario = repo_usuarios.buscar_por_id(db, usuario_id)
        if not usuario.totp_activo:
            raise HTTPException(409, "No tienes activa la verificación en dos pasos.")
        # Las cuentas de Google o Facebook no conocen su contraseña: con el código basta
        if usuario.tiene_password and not auth.password_correcta(usuario, password):
            raise HTTPException(403, "La contraseña no es correcta.")
        if not verificar(usuario, codigo, db):
            db.commit()
            raise HTTPException(403, "El código no es correcto.")
        usuario.totp_activo = False
        usuario.totp_secreto = None
        usuario.totp_respaldo = None
        db.commit()
        email, nombre = usuario.email, usuario.nombre
    correo.enviar_aviso(
        email, "Desactivaste la verificación en dos pasos", f"Hola, {nombre}",
        ["La verificación en dos pasos de tu cuenta de Splitter quedó desactivada."],
        pie="Si no fuiste tú, cambia tu contraseña y vuelve a activarla.",
    )


def respaldo_restante(usuario: Usuario) -> int:
    return len(json.loads(usuario.totp_respaldo or "[]"))
