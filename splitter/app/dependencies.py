"""Quién hace la petición.

La sesión viaja en una cookie HttpOnly (el JavaScript de la página no la puede leer, así
que un script inyectado no puede robarla). También se acepta "Authorization: Bearer"
para clientes de la API y pruebas.
"""
from typing import Optional
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import config
from .models.tablas import Usuario
from .services import auth

_bearer = HTTPBearer(auto_error=False)
COOKIE_SESION = "splitter_sesion"
_METODOS_SEGUROS = {"GET", "HEAD", "OPTIONS"}


def _mismo_origen(request: Request) -> bool:
    """Con la cookie, un POST/PATCH/DELETE debe venir de esta misma página (contra CSRF)."""
    origen = request.headers.get("origin") or request.headers.get("referer")
    if not origen:
        return True  # los navegadores siempre mandan Origin en fetch; sin él no es un navegador
    o = urlparse(origen)
    permitidos = {request.url.netloc}
    if config.PUBLIC_URL:
        permitidos.add(urlparse(config.PUBLIC_URL).netloc)
    permitidos.update(urlparse(x).netloc for x in config.ALLOWED_ORIGINS)
    return o.netloc in permitidos


def _token(request: Request, credenciales: Optional[HTTPAuthorizationCredentials]) -> Optional[str]:
    if credenciales is not None:
        return credenciales.credentials
    token = request.cookies.get(COOKIE_SESION)
    if token and request.method not in _METODOS_SEGUROS and not _mismo_origen(request):
        raise HTTPException(403, "Petición de otro sitio rechazada.")
    return token or None


def token_actual(request: Request, credenciales: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> str:
    token = _token(request, credenciales)
    if token is None:
        raise HTTPException(401, "Inicia sesión para continuar.", headers={"WWW-Authenticate": "Bearer"})
    return token


def usuario_actual(token: str = Depends(token_actual)) -> Usuario:
    return auth.usuario_por_token(token)


def usuario_opcional(
    request: Request, credenciales: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)
) -> Optional[Usuario]:
    """Usuario del token, o None si no hay token. Una cookie vencida cuenta como sin sesión."""
    token = _token(request, credenciales)
    if token is None:
        return None
    if credenciales is None:
        try:
            return auth.usuario_por_token(token)
        except HTTPException:
            return None
    return auth.usuario_por_token(token)


def direccion_base(request: Request) -> str:
    """Dirección de la página: la de .env o la de la petición."""
    return config.PUBLIC_URL or str(request.base_url).rstrip("/")


def es_https(request: Request) -> bool:
    return config.PUBLIC_URL.startswith("https://") or request.url.scheme == "https"


def poner_cookie(respuesta, request: Request, token: str) -> None:
    respuesta.set_cookie(
        COOKIE_SESION,
        token,
        max_age=config.DIAS_SESION * 24 * 3600,
        httponly=True,
        secure=es_https(request),
        samesite="lax",
        path="/",
    )


def quitar_cookie(respuesta, request: Request) -> None:
    respuesta.delete_cookie(COOKIE_SESION, path="/", httponly=True, secure=es_https(request), samesite="lax")
