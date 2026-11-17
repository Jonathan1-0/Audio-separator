"""Códigos de 6 dígitos por correo para confirmar una cuenta nueva.

Al registrarse se envía un código al correo; la cuenta queda "pendiente" hasta que se escribe.
El servidor no guarda el código: devuelve un "pendiente" firmado que lo incluye (como huella),
y la página lo manda de vuelta junto con el código que escribió la persona.
"""
import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException

from .. import config
from ..models.tablas import Usuario
from ..ratelimit import RateLimiter
from . import correo

MINUTOS = 10  # lo que dura un código
DIGITOS = 6
_CLAVE = hashlib.sha256(b"splitter-codigos:" + (config.SECRET_KEY or secrets.token_hex(32)).encode()).digest()
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


def enviar_codigo(usuario: Usuario, motivo: str = "confirmar tu cuenta") -> str:
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
        pie="Si no creaste una cuenta en Splitter, ignora este correo.",
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
