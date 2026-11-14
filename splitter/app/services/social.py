"""Entrar con Google o Facebook (OAuth 2)."""
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request

from fastapi import HTTPException

from .. import config
from ..database import SessionLocal
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
    return {"email": email, "nombre": (perfil.get("name") or email.split("@")[0])[:100]}


def entrar(email: str, nombre: str) -> dict:
    """Abre sesión con ese correo; si no tenía cuenta, la crea."""
    with SessionLocal() as db:
        usuario = repo_usuarios.buscar_por_email(db, email)
        if usuario is None:
            # Sin contraseña propia: se guarda una al azar
            usuario = repo_usuarios.crear(db, email, nombre, auth.crear_hash(secrets.token_urlsafe(32)))
            crear_periodo_gratis(db, usuario.id)
        if usuario.estado != "activo":
            raise HTTPException(403, "Tu cuenta está suspendida.")
        datos = auth.abrir_sesion(db, usuario)
        db.commit()
    return datos
