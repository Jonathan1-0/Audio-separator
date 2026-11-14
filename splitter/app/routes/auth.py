"""Rutas de registro, login y logout."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ..dependencies import direccion_base, token_actual, usuario_actual
from ..models.tablas import Usuario
from ..services import auth, invitados, recuperacion

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


class DatosRecuperar(BaseModel):
    email: str


class DatosRestablecer(BaseModel):
    codigo: str
    password: str


@router.post("/recuperar")
def recuperar(datos: DatosRecuperar, request: Request):
    """Envía el enlace para cambiar la contraseña."""
    recuperacion.pedir(datos.email, invitados.ip_de(request), direccion_base(request))
    return {"mensaje": "Si ese correo tiene cuenta, te enviamos un enlace para cambiar la contraseña."}


@router.post("/restablecer")
def restablecer(datos: DatosRestablecer):
    """Guarda la contraseña nueva."""
    recuperacion.cambiar(datos.codigo, datos.password)
    return {"mensaje": "Tu contraseña se cambió. Ya puedes iniciar sesión."}


@router.post("/logout", status_code=204)
def logout(token: str = Depends(token_actual), _usuario: Usuario = Depends(usuario_actual)):
    auth.logout(token)
