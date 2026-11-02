"""Dependencias de FastAPI para saber quién hace la petición."""
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

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
    """Sin token devuelve None; con un token vencido da 401 igual."""
    if credenciales is None:
        return None
    return auth.usuario_por_token(credenciales.credentials)
