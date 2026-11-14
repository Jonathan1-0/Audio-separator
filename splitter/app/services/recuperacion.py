"""Recuperar la contraseña con un enlace enviado por correo.

El enlace lleva un código firmado: "id.vence.firma". No se guarda en la base. La firma incluye la
contraseña actual (su hash), así que el enlace deja de servir en cuanto la contraseña cambia.
"""
import hashlib
import hmac
import logging
import secrets
import time

from fastapi import HTTPException

from .. import config
from ..database import SessionLocal
from ..models.tablas import Usuario
from ..ratelimit import RateLimiter
from ..repositories import usuarios as repo_usuarios
from . import auth, correo

log = logging.getLogger("splitter.recuperacion")

# Sin clave en .env se inventa una al arrancar.
_CLAVE = (config.SECRET_KEY or secrets.token_hex(32)).encode()
# Como mucho 5 solicitudes por hora desde la misma IP, para que no se use para llenar de correos a alguien.
_por_ip = RateLimiter(5, 3600)
ENLACE_INVALIDO = "El enlace no es válido o ya venció. Pide uno nuevo."


def _firma(usuario: Usuario, vence: int) -> str:
    texto = f"{usuario.id}.{vence}.{usuario.password_hash}".encode()
    return hmac.new(_CLAVE, texto, hashlib.sha256).hexdigest()


def crear_codigo(usuario: Usuario) -> str:
    vence = int(time.time()) + config.MINUTOS_RECUPERACION * 60
    return f"{usuario.id}.{vence}.{_firma(usuario, vence)}"


def pedir(email: str, ip: str, base: str) -> None:
    """Envía el enlace si el correo tiene cuenta. Si no la tiene no hace nada (y no lo dice),
    para que nadie pueda averiguar qué correos están registrados."""
    if _por_ip.acquire(ip) > 0:
        raise HTTPException(429, "Pediste demasiados enlaces. Espera un rato e intenta de nuevo.")
    with SessionLocal() as db:
        usuario = repo_usuarios.buscar_por_email(db, email.strip().lower())
    if usuario is None or usuario.estado != "activo":
        return
    enlace = f"{base}/#restablecer={crear_codigo(usuario)}"
    texto = (
        f"Hola, {usuario.nombre}:\n\n"
        "Recibimos una solicitud para cambiar la contraseña de tu cuenta de Splitter.\n"
        f"Abre este enlace para elegir una nueva (sirve {config.MINUTOS_RECUPERACION} minutos):\n\n"
        f"{enlace}\n\n"
        "Si no fuiste tú, ignora este correo: tu contraseña sigue igual.\n"
    )
    try:
        correo.enviar(usuario.email, "Cambia tu contraseña de Splitter", texto)
    except Exception:  # el correo falló: se registra, pero la respuesta al usuario es la misma
        log.exception("No se pudo enviar el correo de recuperación")


def cambiar(codigo: str, password_nueva: str) -> None:
    """Revisa el código del enlace y guarda la contraseña nueva."""
    auth.validar_password(password_nueva)
    partes = codigo.split(".")
    if len(partes) != 3 or not partes[0].isdigit() or not partes[1].isdigit():
        raise HTTPException(400, ENLACE_INVALIDO)
    usuario_id, vence, firma = int(partes[0]), int(partes[1]), partes[2]
    with SessionLocal() as db:
        usuario = repo_usuarios.buscar_por_id(db, usuario_id)
        if usuario is None or vence < time.time() or not hmac.compare_digest(firma, _firma(usuario, vence)):
            raise HTTPException(400, ENLACE_INVALIDO)
        repo_usuarios.cambiar_password(db, usuario, auth.crear_hash(password_nueva))
        repo_usuarios.borrar_sesiones_de(db, usuario.id)  # se cierra la sesión en todos lados
        db.commit()
