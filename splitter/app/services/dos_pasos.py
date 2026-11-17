"""Verificación en dos pasos por correo.

Cuando hace falta (iniciar sesión, activarla o desactivarla) se envía un código de 6 dígitos
al correo de la cuenta. El servidor no guarda el código: devuelve un "pendiente" firmado que
lo incluye (como huella), y la página lo manda de vuelta junto con el código que escribió la persona.

En la base se usa la columna totp_activo para saber si está activa (las columnas totp_secreto
y totp_respaldo eran de la versión con app de autenticación y ya no se usan).
"""
import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException

from .. import config
from ..database import SessionLocal
from ..models.tablas import Usuario
from ..ratelimit import RateLimiter
from ..repositories import usuarios as repo_usuarios
from . import correo

MINUTOS = 10  # lo que dura un código
DIGITOS = 6
_CLAVE = hashlib.sha256(b"splitter-dos-pasos:" + (config.SECRET_KEY or secrets.token_hex(32)).encode()).digest()
# Contra adivinar el código y contra llenar el correo de alguien con códigos
_fallos = RateLimiter(5, MINUTOS * 60, config.DATA_DIR / "limite_codigos_fallidos.json")
_envios = RateLimiter(5, 15 * 60, config.DATA_DIR / "limite_codigos_enviados.json")
# Pendientes ya usados: un código sirve una sola vez
_usados: dict = {}


def _firma(usuario_id: int, vence: int, codigo: str) -> str:
    return hmac.new(_CLAVE, f"{usuario_id}.{vence}.{codigo}".encode(), hashlib.sha256).hexdigest()


def correo_oculto(email: str) -> str:
    nombre, _, dominio = email.partition("@")
    return f"{nombre[:2]}{'•' * max(1, min(len(nombre) - 2, 6))}@{dominio}"


def enviar_codigo(usuario: Usuario, motivo: str = "iniciar sesión") -> str:
    """Envía un código al correo de la cuenta y devuelve el pendiente firmado."""
    if _envios.acquire(str(usuario.id)) > 0:
        raise HTTPException(429, "Pediste demasiados códigos. Espera unos minutos e intenta de nuevo.")
    codigo = str(secrets.randbelow(10 ** DIGITOS)).zfill(DIGITOS)
    vence = int(time.time()) + MINUTOS * 60
    correo.enviar_aviso(
        usuario.email,
        f"Tu código de Splitter: {codigo}",
        f"Hola, {usuario.nombre}",
        [f"Tu código para {motivo} es:", codigo, f"Vence en {MINUTOS} minutos."],
        pie="Si no fuiste tú, cambia tu contraseña: alguien intentó entrar a tu cuenta.",
    )
    return f"{usuario.id}.{vence}.{_firma(usuario.id, vence, codigo)}"


def verificar(usuario_id: int, pendiente: str, codigo: str) -> bool:
    """Revisa que el código corresponda al pendiente, que no haya vencido ni se haya usado."""
    codigo = (codigo or "").strip().replace(" ", "")
    partes = (pendiente or "").split(".")
    if len(partes) != 3 or not partes[0].isdigit() or not partes[1].isdigit() or int(partes[0]) != usuario_id:
        return False
    if _fallos.espera(str(usuario_id)) > 0:
        raise HTTPException(429, "Demasiados códigos incorrectos. Pide uno nuevo en unos minutos.")
    vence = int(partes[1])
    if vence < time.time():
        raise HTTPException(401, "El código venció. Pide uno nuevo.")
    if not (codigo.isdigit() and len(codigo) == DIGITOS) or not hmac.compare_digest(partes[2], _firma(usuario_id, vence, codigo)):
        _fallos.acquire(str(usuario_id))
        return False
    if partes[2] in _usados:
        return False
    _usados[partes[2]] = vence
    for clave, hasta in list(_usados.items()):  # se olvidan los que ya vencieron
        if hasta < time.time():
            _usados.pop(clave, None)
    _fallos.limpiar(str(usuario_id))
    return True


def iniciar(usuario_id: int, activar: bool) -> dict:
    """Manda el código para activar o desactivar."""
    with SessionLocal() as db:
        usuario = repo_usuarios.buscar_por_id(db, usuario_id)
    if activar and usuario.totp_activo:
        raise HTTPException(409, "Ya tienes activa la verificación en dos pasos.")
    if not activar and not usuario.totp_activo:
        raise HTTPException(409, "No tienes activa la verificación en dos pasos.")
    pendiente = enviar_codigo(usuario, "activar la verificación en dos pasos" if activar else "desactivar la verificación en dos pasos")
    return {"pendiente": pendiente, "correo": correo_oculto(usuario.email)}


def cambiar(usuario_id: int, activar: bool, pendiente: str, codigo: str) -> None:
    """Activa o desactiva con el código que llegó al correo."""
    if not verificar(usuario_id, pendiente, codigo):
        raise HTTPException(400, "El código no es correcto.")
    with SessionLocal() as db:
        usuario = repo_usuarios.buscar_por_id(db, usuario_id)
        usuario.totp_activo = activar
        usuario.totp_secreto = None
        usuario.totp_respaldo = None
        if activar:
            usuario.email_verificado = True  # el código llegó a su correo
        db.commit()
        email, nombre = usuario.email, usuario.nombre
    correo.enviar_aviso(
        email,
        "Activaste la verificación en dos pasos" if activar else "Desactivaste la verificación en dos pasos",
        f"Hola, {nombre}",
        ["Desde ahora, al iniciar sesión te enviaremos un código a este correo." if activar
         else "Tu cuenta de Splitter ya no pedirá un código al iniciar sesión."],
        pie="Si no fuiste tú, cambia tu contraseña de inmediato.",
    )
