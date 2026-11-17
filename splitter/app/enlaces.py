"""Enlaces firmados para escuchar y descargar las pistas de una cuenta.

El navegador no manda el token en <audio src>, <a href> ni EventSource, así que
la API entrega al dueño direcciones con una firma. Sin la firma (o el token del
dueño) nadie más puede escuchar ni bajar ese trabajo.
"""
import hashlib
import hmac
import secrets

from . import config

_CLAVE = hashlib.sha256(b"splitter-enlaces:" + (config.SECRET_KEY or secrets.token_hex(32)).encode()).digest()


def firma(job_id: str) -> str:
    return hmac.new(_CLAVE, job_id.encode(), hashlib.sha256).hexdigest()[:40]


def firma_valida(job_id: str, valor: str) -> bool:
    return bool(valor) and hmac.compare_digest(valor, firma(job_id))


def firmar(job_id: str, ruta: str) -> str:
    """Agrega la firma a una dirección del trabajo."""
    return f"{ruta}?firma={firma(job_id)}"
