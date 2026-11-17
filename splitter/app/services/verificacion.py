"""Confirmar el correo: al registrarse y al cambiarlo desde Perfil.

El enlace lleva un código firmado. Para un cambio de correo, el código lleva también
el correo nuevo, y el cambio solo se guarda cuando se abre el enlace que llegó ahí.
"""
import base64
import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from .. import config
from ..database import SessionLocal
from ..models.tablas import Usuario
from ..ratelimit import RateLimiter
from ..repositories import usuarios as repo_usuarios
from . import correo

_CLAVE = hashlib.sha256(b"splitter-verificacion:" + (config.SECRET_KEY or secrets.token_hex(32)).encode()).digest()
_por_cuenta = RateLimiter(config.CORREOS_POR_CUENTA, 3600, config.DATA_DIR / "limite_correos.json")
ENLACE_INVALIDO = "El enlace no es válido o ya venció. Pide uno nuevo desde tu perfil."


def _b64(texto: str) -> str:
    return base64.urlsafe_b64encode(texto.encode()).decode().rstrip("=")


def _de_b64(texto: str) -> str:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4)).decode()


def _firma(usuario_id: int, vence: int, email: str) -> str:
    return hmac.new(_CLAVE, f"{usuario_id}.{vence}.{email}".encode(), hashlib.sha256).hexdigest()


def crear_codigo(usuario_id: int, email: str) -> str:
    vence = int(time.time()) + config.HORAS_VERIFICACION * 3600
    return f"{usuario_id}.{vence}.{_b64(email)}.{_firma(usuario_id, vence, email)}"


def _limitar(usuario_id: int) -> None:
    if _por_cuenta.acquire(str(usuario_id)) > 0:
        raise HTTPException(429, "Pediste demasiados correos. Espera un rato e intenta de nuevo.")


def enviar_confirmacion(usuario: Usuario, base: str) -> None:
    """Correo para confirmar el correo actual de la cuenta."""
    _limitar(usuario.id)
    enlace = f"{base}/#verificar={crear_codigo(usuario.id, usuario.email)}"
    correo.enviar_aviso(
        usuario.email,
        "Confirma tu correo de Splitter",
        f"Hola, {usuario.nombre}",
        ["Gracias por crear tu cuenta. Confirma que este correo es tuyo para poder recuperar tu cuenta "
         "y recibir los avisos de tu plan.",
         f"El enlace sirve {config.HORAS_VERIFICACION} horas."],
        "Confirmar mi correo",
        enlace,
        "Si no creaste una cuenta en Splitter, ignora este correo.",
    )


def pedir_cambio(usuario: Usuario, email_nuevo: str, base: str) -> None:
    """Correo al correo nuevo; el cambio se guarda al abrir el enlace."""
    _limitar(usuario.id)
    enlace = f"{base}/#verificar={crear_codigo(usuario.id, email_nuevo)}"
    correo.enviar_aviso(
        email_nuevo,
        "Confirma tu nuevo correo de Splitter",
        f"Hola, {usuario.nombre}",
        [f"Pediste usar este correo en tu cuenta de Splitter en lugar de {usuario.email}.",
         f"El cambio se guarda cuando abras el enlace. Sirve {config.HORAS_VERIFICACION} horas."],
        "Usar este correo",
        enlace,
        "Si no fuiste tú, ignora este correo: la cuenta no cambia.",
    )


def confirmar(codigo: str) -> dict:
    """Abre el enlace: confirma el correo o guarda el correo nuevo."""
    partes = codigo.split(".")
    if len(partes) != 4 or not partes[0].isdigit() or not partes[1].isdigit():
        raise HTTPException(400, ENLACE_INVALIDO)
    usuario_id, vence = int(partes[0]), int(partes[1])
    try:
        email = _de_b64(partes[2])
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, ENLACE_INVALIDO)
    if vence < time.time() or not hmac.compare_digest(partes[3], _firma(usuario_id, vence, email)):
        raise HTTPException(400, ENLACE_INVALIDO)

    with SessionLocal() as db:
        usuario = repo_usuarios.buscar_por_id(db, usuario_id)
        if usuario is None or usuario.estado != "activo":
            raise HTTPException(400, ENLACE_INVALIDO)
        anterior = usuario.email
        if email != anterior:
            otro = repo_usuarios.buscar_por_email(db, email)
            if otro is not None:
                raise HTTPException(409, "Ese correo ya lo usa otra cuenta.")
            usuario.email = email
            # Facebook confirmó el correo viejo, no este: ya no entra con Facebook
            usuario.proveedor = "email"
        usuario.email_verificado = True
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Ese correo ya lo usa otra cuenta.")
        nombre = usuario.nombre

    if email != anterior:
        correo.enviar_aviso(
            anterior,
            "Cambiaste el correo de tu cuenta de Splitter",
            f"Hola, {nombre}",
            [f"Tu cuenta de Splitter ahora usa el correo {email}. Desde ahora inicias sesión con ese correo."],
            pie="Si no fuiste tú, escríbenos de inmediato respondiendo este correo.",
        )
        return {"mensaje": f"Listo: tu cuenta ahora usa {email}.", "email": email}
    return {"mensaje": "Listo: tu correo quedó confirmado.", "email": email}
