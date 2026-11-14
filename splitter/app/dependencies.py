"""Quién hace la petición."""
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import config
from .models.tablas import Usuario
from .services import auth

_bearer = HTTPBearer(auto_error=False)


def token_actual(credenciales: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> str:
    if credenciales is None:
        raise HTTPException(401, "Inicia sesión para continuar.", headers={"WWW-Authenticate": "Bearer"})
    return credenciales.credentials


def usuario_actual(token: str = Depends(token_actual)) -> Usuario:
    return auth.usuario_por_token(token)


def usuario_opcional(credenciales: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> Optional[Usuario]:
    """Usuario del token, o None si no hay token."""
    if credenciales is None:
        return None
    return auth.usuario_por_token(credenciales.credentials)


def direccion_base(request: Request) -> str:
    """Dirección de la página: la de .env o la de la petición."""
    return config.PUBLIC_URL or str(request.base_url).rstrip("/")
