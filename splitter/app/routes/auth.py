"""Rutas de registro, login y logout."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..dependencies import token_actual, usuario_actual
from ..models.tablas import Usuario
from ..services import auth

router = APIRouter(prefix="/auth", tags=["auth"])


class DatosRegistro(BaseModel):
    email: str
    nombre: str
    password: str


class DatosLogin(BaseModel):
    email: str
    password: str


@router.post("/registro", status_code=201)
def registro(datos: DatosRegistro):
    """Crea una cuenta con el plan gratis."""
    return auth.registrar(datos.email, datos.nombre, datos.password)


@router.post("/login")
def login(datos: DatosLogin):
    return auth.login(datos.email, datos.password)


@router.post("/logout", status_code=204)
def logout(token: str = Depends(token_actual), _usuario: Usuario = Depends(usuario_actual)):
    auth.logout(token)
