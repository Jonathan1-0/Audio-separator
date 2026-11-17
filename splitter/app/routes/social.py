"""Rutas para entrar con Google o Facebook, y para conectar Google a una cuenta."""
import secrets
import urllib.parse
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from ..dependencies import direccion_base, poner_cookie, usuario_actual, usuario_opcional
from ..models.tablas import Usuario
from ..services import auth, social

router = APIRouter(prefix="/auth/social", tags=["auth"])
COOKIE_ESTADO = "splitter_estado"
COOKIE_CONECTAR = "splitter_conectar"


@router.get("")
def proveedores():
    """Qué botones puede mostrar la página."""
    return social.disponibles()


@router.get("/{proveedor}")
def iniciar(
    proveedor: str, request: Request, conectar: bool = False, usuario: Optional[Usuario] = Depends(usuario_opcional)
):
    """Manda al usuario a Google o Facebook. Con ?conectar=1 la conecta a la cuenta abierta."""
    if conectar and usuario is None:
        return _volver_con_error("Inicia sesión para conectar tu cuenta.")
    estado = secrets.token_urlsafe(24)
    respuesta = RedirectResponse(social.url_de_inicio(proveedor, estado, direccion_base(request)))
    respuesta.set_cookie(COOKIE_ESTADO, estado, max_age=600, httponly=True, samesite="lax")
    if conectar:
        respuesta.set_cookie(COOKIE_CONECTAR, "1", max_age=600, httponly=True, samesite="lax")
    else:
        respuesta.delete_cookie(COOKIE_CONECTAR)
    return respuesta


def _volver_con_error(mensaje: str) -> RedirectResponse:
    return RedirectResponse(f"/#error={urllib.parse.quote(mensaje)}")


@router.get("/{proveedor}/regreso")
def regreso(
    proveedor: str,
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    usuario: Optional[Usuario] = Depends(usuario_opcional),
):
    """Regreso del proveedor: abre la sesión (o conecta Google) y vuelve al inicio."""
    guardado = request.cookies.get(COOKIE_ESTADO, "")
    conectar = request.cookies.get(COOKIE_CONECTAR) == "1"
    if error or not code:
        respuesta = _volver_con_error("Se canceló el acceso. Puedes intentarlo de nuevo.")
    elif not guardado or not secrets.compare_digest(guardado, state):
        respuesta = _volver_con_error("El acceso tardó demasiado o no empezó en esta página. Intenta de nuevo.")
    else:
        try:
            perfil = social.obtener_perfil(proveedor, code, direccion_base(request))
            if conectar:
                if usuario is None:
                    raise HTTPException(401, "Tu sesión se cerró. Inicia sesión y vuelve a conectar tu cuenta.")
                social.conectar(usuario.id, proveedor, perfil["id"])
                respuesta = RedirectResponse(f"/#conectado={proveedor}")
            else:
                sesion = social.entrar(perfil["email"], perfil["nombre"], proveedor, perfil["id"])
                # El token queda en la cookie HttpOnly; en la dirección solo va el identificador
                respuesta = RedirectResponse(f"/#sesion={sesion['sesion']}")
                poner_cookie(respuesta, request, sesion["token"])
        except social.DosPasosPendiente as pendiente:
            respuesta = RedirectResponse(f"/#dos-pasos={pendiente.pendiente}")
        except HTTPException as fallo:
            respuesta = _volver_con_error(str(fallo.detail))
    respuesta.delete_cookie(COOKIE_ESTADO)
    respuesta.delete_cookie(COOKIE_CONECTAR)
    return respuesta


class DatosDosPasos(BaseModel):
    pendiente: str
    codigo: str


@router.post("/dos-pasos")
def dos_pasos(datos: DatosDosPasos, request: Request):
    """Segundo paso al entrar con Google o Facebook en una cuenta con verificación en dos pasos."""
    sesion = social.terminar_dos_pasos(datos.pendiente, datos.codigo)
    respuesta = JSONResponse(auth.publico(sesion))
    poner_cookie(respuesta, request, sesion["token"])
    return respuesta


@router.post("/{proveedor}/desconectar", status_code=204)
def desconectar(proveedor: str, usuario: Usuario = Depends(usuario_actual)):
    social.desconectar(usuario.id, proveedor)
