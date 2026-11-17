"""Rutas de registro, login, logout y perfil."""
from typing import Optional

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from .. import config

from ..dependencies import direccion_base, poner_cookie, quitar_cookie, token_actual, usuario_actual
from ..models.tablas import Usuario
from ..services import auth, invitados, perfil, recuperacion, verificacion

router = APIRouter(prefix="/auth", tags=["auth"])


class DatosRegistro(BaseModel):
    email: str
    nombre: str
    password: str


class DatosLogin(BaseModel):
    email: str
    password: str


@router.post("/registro", status_code=201)
def registro(datos: DatosRegistro, request: Request):
    """Crea la cuenta y envía al correo el código para confirmarla."""
    usuario = auth.registrar(datos.email, datos.nombre, datos.password, invitados.ip_de(request))
    return {"email": usuario.email, "nombre": usuario.nombre, **auth.pedir_confirmacion(usuario)}


class DatosConfirmar(BaseModel):
    pendiente: str
    codigo: str


@router.post("/registro/confirmar")
def confirmar_registro(datos: DatosConfirmar, request: Request):
    """Con el código del correo la cuenta queda activa y se abre la sesión."""
    sesion = auth.confirmar_registro(datos.pendiente, datos.codigo)
    respuesta = JSONResponse(auth.publico(sesion))
    poner_cookie(respuesta, request, sesion["token"])
    return respuesta


class DatosReenviar(BaseModel):
    email: str


@router.post("/registro/reenviar")
def reenviar_codigo(datos: DatosReenviar):
    return auth.reenviar_confirmacion(datos.email)


@router.post("/login")
def login(datos: DatosLogin, request: Request):
    """Abre la sesión: el token queda en una cookie HttpOnly."""
    sesion = auth.login(datos.email, datos.password, invitados.ip_de(request))
    respuesta = JSONResponse(auth.publico(sesion))
    poner_cookie(respuesta, request, sesion["token"])
    return respuesta


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
def logout(request: Request, token: str = Depends(token_actual)):
    auth.logout(token)
    respuesta = Response(status_code=204)
    quitar_cookie(respuesta, request)
    return respuesta


class DatosPerfil(BaseModel):
    nombre: Optional[str] = None
    email: Optional[str] = None
    telefono: Optional[str] = None


@router.patch("/perfil")
def cambiar_perfil(datos: DatosPerfil, request: Request, usuario: Usuario = Depends(usuario_actual)):
    """Cambia un dato por llamada; devuelve el perfil como quedó.
    El correo cambia hasta que se abre el enlace que le llega (ver "email_pendiente")."""
    return perfil.cambiar_dato(usuario.id, datos.model_dump(), direccion_base(request))


@router.put("/perfil/foto")
async def cambiar_foto(foto: UploadFile = File(...), usuario: Usuario = Depends(usuario_actual)):
    contenido = await foto.read(config.MAX_FOTO_BYTES + 1)
    return await run_in_threadpool(perfil.guardar_foto, usuario.id, contenido)


@router.get("/fotos/{nombre}")
def ver_foto(nombre: str):
    ruta = perfil.ruta_foto(nombre)
    tipo = perfil.TIPOS_FOTO[ruta.suffix.lstrip(".")]
    # El nombre cambia con cada foto nueva, así que se puede guardar en caché
    return FileResponse(ruta, media_type=tipo, headers={"Cache-Control": "private, max-age=86400"})


class DatosPassword(BaseModel):
    actual: str
    nueva: str


@router.post("/password", status_code=204)
def cambiar_password(
    datos: DatosPassword, token: str = Depends(token_actual), usuario: Usuario = Depends(usuario_actual)
):
    """Cambia la contraseña y cierra las otras sesiones."""
    perfil.cambiar_password(usuario.id, token, datos.actual, datos.nueva)


class DatosVerificar(BaseModel):
    codigo: str


@router.post("/verificar")
def verificar(datos: DatosVerificar):
    """Abre el enlace del correo: confirma el correo o guarda el nuevo."""
    return verificacion.confirmar(datos.codigo)


@router.post("/verificar/reenviar")
def reenviar_verificacion(request: Request, usuario: Usuario = Depends(usuario_actual)):
    if usuario.email_verificado:
        return {"mensaje": "Tu correo ya está confirmado."}
    verificacion.enviar_confirmacion(usuario, direccion_base(request))
    return {"mensaje": f"Te enviamos un enlace a {usuario.email}."}


@router.post("/logout-todo", status_code=204)
def cerrar_todas(request: Request, usuario: Usuario = Depends(usuario_actual)):
    """Cierra la sesión en todos los dispositivos."""
    perfil.cerrar_todas(usuario.id)
    respuesta = Response(status_code=204)
    quitar_cookie(respuesta, request)
    return respuesta


class DatosBorrar(BaseModel):
    password: str = ""
    confirmacion: str = ""  # el correo, para cuentas de Google o Facebook


@router.delete("/cuenta", status_code=204)
def borrar_cuenta(datos: DatosBorrar, request: Request, usuario: Usuario = Depends(usuario_actual)):
    """Borra la cuenta, sus audios y sus datos personales."""
    perfil.borrar_cuenta(usuario.id, datos.password, datos.confirmacion, request.app.state.manager.delete)
    respuesta = Response(status_code=204)
    quitar_cookie(respuesta, request)
    return respuesta
