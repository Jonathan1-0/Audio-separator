"""Rutas para entrar con Google o Facebook."""
import secrets
import urllib.parse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..dependencies import direccion_base
from ..services import social

router = APIRouter(prefix="/auth/social", tags=["auth"])
COOKIE_ESTADO = "splitter_estado"


@router.get("")
def proveedores():
    """Qué botones puede mostrar la página."""
    return social.disponibles()


@router.get("/{proveedor}")
def iniciar(proveedor: str, request: Request):
    """Manda al usuario a Google o Facebook."""
    estado = secrets.token_urlsafe(24)
    respuesta = RedirectResponse(social.url_de_inicio(proveedor, estado, direccion_base(request)))
    respuesta.set_cookie(COOKIE_ESTADO, estado, max_age=600, httponly=True, samesite="lax")
    return respuesta


def _volver_con_error(mensaje: str) -> RedirectResponse:
    return RedirectResponse(f"/#error={urllib.parse.quote(mensaje)}")


@router.get("/{proveedor}/regreso")
def regreso(proveedor: str, request: Request, code: str = "", state: str = "", error: str = ""):
    """Regreso del proveedor: abre la sesión y vuelve al inicio."""
    guardado = request.cookies.get(COOKIE_ESTADO, "")
    if error or not code:
        respuesta = _volver_con_error("Se canceló el acceso. Puedes intentarlo de nuevo.")
    elif not guardado or not secrets.compare_digest(guardado, state):
        respuesta = _volver_con_error("El acceso tardó demasiado o no empezó en esta página. Intenta de nuevo.")
    else:
        try:
            perfil = social.obtener_perfil(proveedor, code, direccion_base(request))
            sesion = social.entrar(perfil["email"], perfil["nombre"])
            # El token va después del "#" para que no llegue a ningún servidor
            respuesta = RedirectResponse(f"/#sesion={sesion['token']}")
        except HTTPException as fallo:
            respuesta = _volver_con_error(str(fallo.detail))
    respuesta.delete_cookie(COOKIE_ESTADO)
    return respuesta
