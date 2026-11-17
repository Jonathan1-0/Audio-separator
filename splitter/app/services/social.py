"""Entrar con Google o Facebook (OAuth 2)."""
import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi import HTTPException
from sqlalchemy import select

from .. import config
from ..database import SessionLocal
from ..models.tablas import Usuario
from ..repositories import usuarios as repo_usuarios
from . import auth
from .cuotas import crear_periodo_gratis

PROVEEDORES = {
    "google": {
        "nombre": "Google",
        "id": config.GOOGLE_CLIENT_ID,
        "secreto": config.GOOGLE_CLIENT_SECRET,
        "url_permiso": "https://accounts.google.com/o/oauth2/v2/auth",
        "url_token": "https://oauth2.googleapis.com/token",
        "url_perfil": "https://openidconnect.googleapis.com/v1/userinfo",
        "permisos": "openid email profile",
    },
    "facebook": {
        "nombre": "Facebook",
        "id": config.FACEBOOK_APP_ID,
        "secreto": config.FACEBOOK_APP_SECRET,
        "url_permiso": "https://www.facebook.com/v21.0/dialog/oauth",
        "url_token": "https://graph.facebook.com/v21.0/oauth/access_token",
        "url_perfil": "https://graph.facebook.com/me?fields=name,email",
        "permisos": "email,public_profile",
    },
}


def disponibles() -> dict:
    """Proveedores que tienen sus claves en .env."""
    return {clave: bool(p["id"] and p["secreto"]) for clave, p in PROVEEDORES.items()}


def _proveedor(clave: str) -> dict:
    proveedor = PROVEEDORES.get(clave)
    if proveedor is None:
        raise HTTPException(404, "Ese proveedor no existe.")
    if not (proveedor["id"] and proveedor["secreto"]):
        raise HTTPException(503, f"El acceso con {proveedor['nombre']} todavía no está configurado.")
    return proveedor


def _url_regreso(clave: str, base: str) -> str:
    """Dirección a la que regresa el proveedor."""
    return f"{base}/auth/social/{clave}/regreso"


def url_de_inicio(clave: str, estado: str, base: str) -> str:
    """Dirección del proveedor para pedir permiso."""
    proveedor = _proveedor(clave)
    datos = {
        "client_id": proveedor["id"],
        "redirect_uri": _url_regreso(clave, base),
        "response_type": "code",
        "scope": proveedor["permisos"],
        "state": estado,
    }
    return f"{proveedor['url_permiso']}?{urllib.parse.urlencode(datos)}"


def _pedir_json(url: str, datos: dict = None, permiso: str = "") -> dict:
    """Llama al proveedor. Con `datos` es POST; sin ellos, GET."""
    cuerpo = urllib.parse.urlencode(datos).encode() if datos else None
    peticion = urllib.request.Request(url, data=cuerpo, headers={"Accept": "application/json"})
    if permiso:
        peticion.add_header("Authorization", f"Bearer {permiso}")
    try:
        with urllib.request.urlopen(peticion, timeout=15) as respuesta:
            return json.loads(respuesta.read().decode())
    except (urllib.error.URLError, ValueError):
        raise HTTPException(502, "No se pudo completar el acceso con ese proveedor. Intenta de nuevo.")


def obtener_perfil(clave: str, code: str, base: str) -> dict:
    """Cambia el code por el correo y el nombre."""
    proveedor = _proveedor(clave)
    respuesta = _pedir_json(proveedor["url_token"], {
        "client_id": proveedor["id"],
        "client_secret": proveedor["secreto"],
        "redirect_uri": _url_regreso(clave, base),
        "grant_type": "authorization_code",
        "code": code,
    })
    permiso = respuesta.get("access_token")
    if not permiso:
        raise HTTPException(502, "No se pudo completar el acceso con ese proveedor. Intenta de nuevo.")
    perfil = _pedir_json(proveedor["url_perfil"], permiso=permiso)
    email = (perfil.get("email") or "").strip().lower()
    # Google debe confirmar que el correo está verificado
    if not email or (clave == "google" and not perfil.get("email_verified")):
        raise HTTPException(400, f"{proveedor['nombre']} no compartió un correo verificado. Usa tu correo y contraseña.")
    return {
        "email": email,
        "nombre": (perfil.get("name") or email.split("@")[0])[:100],
        # Identificador fijo de la cuenta en el proveedor (no cambia aunque cambie el correo)
        "id": str(perfil.get("sub") or perfil.get("id") or "")[:64],
    }


class DosPasosPendiente(Exception):
    """La cuenta tiene verificación en dos pasos: falta el código."""

    def __init__(self, pendiente: str) -> None:
        self.pendiente = pendiente


_CLAVE = hashlib.sha256(b"splitter-social-2fa:" + (config.SECRET_KEY or secrets.token_hex(32)).encode()).digest()
MINUTOS_PENDIENTE = 5


def _firmar_pendiente(usuario_id: int) -> str:
    vence = int(time.time()) + MINUTOS_PENDIENTE * 60
    firma = hmac.new(_CLAVE, f"{usuario_id}.{vence}".encode(), hashlib.sha256).hexdigest()
    return f"{usuario_id}.{vence}.{firma}"


def _leer_pendiente(pendiente: str) -> int:
    partes = pendiente.split(".")
    if len(partes) == 3 and partes[0].isdigit() and partes[1].isdigit() and int(partes[1]) >= time.time():
        esperada = hmac.new(_CLAVE, f"{partes[0]}.{partes[1]}".encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(partes[2], esperada):
            return int(partes[0])
    raise HTTPException(400, "El acceso tardó demasiado. Vuelve a entrar con Google o Facebook.")


def _columna(proveedor: str):
    """Columna con el identificador de esa red (no cambia aunque cambie el correo)."""
    return {"google": Usuario.google_id, "facebook": Usuario.facebook_id}[proveedor]


def entrar(email: str, nombre: str, proveedor: str = "google", proveedor_id: str = "") -> dict:
    """Abre sesión; si no había cuenta, la crea.

    - Se busca primero por el identificador de la red: así entra aunque cambie el correo.
    - Una cuenta que ya existía con ese correo no se abre sola: hay que entrar como siempre
      y conectar la red desde el perfil (Facebook ni siquiera confirma que el correo sea de quien entra).
    - Con verificación en dos pasos lanza DosPasosPendiente: la sesión se abre al dar el código.
    """
    nombre_red = PROVEEDORES[proveedor]["nombre"]
    with SessionLocal() as db:
        usuario = None
        if proveedor_id:
            usuario = db.scalar(select(Usuario).where(_columna(proveedor) == proveedor_id))
        if usuario is None:
            usuario = repo_usuarios.buscar_por_email(db, email)
            if usuario is None:
                # Sin contraseña propia: se guarda una al azar y se marca que no tiene
                usuario = repo_usuarios.crear(db, email, nombre, auth.crear_hash(secrets.token_urlsafe(32)))
                usuario.proveedor = proveedor
                usuario.tiene_password = False
                setattr(usuario, f"{proveedor}_id", proveedor_id or None)
                usuario.email_verificado = proveedor == "google"  # Google confirma el correo; Facebook no
                crear_periodo_gratis(db, usuario.id)
            elif usuario.proveedor == proveedor and not getattr(usuario, f"{proveedor}_id"):
                # Cuenta creada con esta red antes de guardar su identificador
                setattr(usuario, f"{proveedor}_id", proveedor_id or None)
            else:
                raise HTTPException(
                    409,
                    f"Ya tienes una cuenta con ese correo. Entra con tu correo y contraseña, "
                    f"y conecta {nombre_red} desde tu perfil para usarlo la próxima vez.",
                )
        if usuario.estado != "activo":
            raise HTTPException(403, "Tu cuenta está suspendida.")
        if usuario.totp_activo:
            db.commit()
            raise DosPasosPendiente(_firmar_pendiente(usuario.id))
        datos = auth.abrir_sesion(db, usuario)
        db.commit()
    return datos


def terminar_dos_pasos(pendiente: str, codigo: str) -> dict:
    """Segundo paso de entrar con Google o Facebook."""
    from . import dos_pasos

    usuario_id = _leer_pendiente(pendiente)
    with SessionLocal() as db:
        usuario = repo_usuarios.buscar_por_id(db, usuario_id)
        if usuario is None or usuario.estado != "activo":
            raise HTTPException(403, "Tu cuenta está suspendida.")
        if not dos_pasos.verificar(usuario, codigo, db):
            db.commit()
            raise HTTPException(401, "El código no es correcto.")
        datos = auth.abrir_sesion(db, usuario)
        db.commit()
    return datos


def conectar(usuario_id: int, proveedor: str, proveedor_id: str) -> None:
    nombre_red = PROVEEDORES[proveedor]["nombre"]
    if not proveedor_id:
        raise HTTPException(400, f"{nombre_red} no compartió tu cuenta. Intenta de nuevo.")
    with SessionLocal() as db:
        otro = db.scalar(select(Usuario).where(_columna(proveedor) == proveedor_id))
        if otro is not None and otro.id != usuario_id:
            raise HTTPException(409, f"Esa cuenta de {nombre_red} ya está conectada a otra cuenta de Splitter.")
        usuario = repo_usuarios.buscar_por_id(db, usuario_id)
        setattr(usuario, f"{proveedor}_id", proveedor_id)
        db.commit()


def desconectar(usuario_id: int, proveedor: str) -> None:
    """Solo si queda otra forma de entrar: contraseña propia u otra red conectada."""
    if proveedor not in PROVEEDORES:
        raise HTTPException(404, "Ese proveedor no existe.")
    nombre_red = PROVEEDORES[proveedor]["nombre"]
    with SessionLocal() as db:
        usuario = repo_usuarios.buscar_por_id(db, usuario_id)
        otra = "facebook" if proveedor == "google" else "google"
        if not usuario.tiene_password and not getattr(usuario, f"{otra}_id"):
            raise HTTPException(409, f"Crea una contraseña antes de desconectar {nombre_red}: si no, no podrías volver a entrar.")
        setattr(usuario, f"{proveedor}_id", None)
        db.commit()
