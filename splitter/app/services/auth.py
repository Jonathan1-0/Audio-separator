"""Registro, inicio y cierre de sesión."""
import secrets
from datetime import timedelta

import bcrypt
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from .. import config
from ..database import SessionLocal, ahora_utc
from ..models.tablas import Usuario
from ..repositories import usuarios as repo_usuarios
from .cuotas import crear_periodo_gratis

MAX_BYTES_PASSWORD = 72  # bcrypt no acepta más


def _validar_datos(email: str, nombre: str, password: str) -> None:
    """Rechaza datos de registro inválidos."""
    if "@" not in email or "." not in email.rsplit("@", 1)[-1] or len(email) > 255:
        raise HTTPException(400, "El email no es válido.")
    if not nombre or len(nombre) > 100:
        raise HTTPException(400, "El nombre debe tener entre 1 y 100 caracteres.")
    if len(password) < 8 or len(password.encode()) > MAX_BYTES_PASSWORD:
        raise HTTPException(400, "La contraseña debe tener entre 8 y 72 caracteres.")


def registrar(email: str, nombre: str, password: str) -> dict:
    """Crea el usuario con su suscripción gratis."""
    email, nombre = email.strip().lower(), nombre.strip()
    _validar_datos(email, nombre, password)
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    with SessionLocal() as db:
        if repo_usuarios.buscar_por_email(db, email) is not None:
            raise HTTPException(409, "Ya existe una cuenta con ese email.")
        try:
            usuario = repo_usuarios.crear(db, email, nombre, password_hash)
            crear_periodo_gratis(db, usuario.id)
            db.commit()
        except IntegrityError:  # dos registros iguales a la vez
            db.rollback()
            raise HTTPException(409, "Ya existe una cuenta con ese email.")
    return {"id": usuario.id, "email": usuario.email, "nombre": usuario.nombre}


def login(email: str, password: str) -> dict:
    """Revisa la contraseña y crea una sesión de 7 días."""
    with SessionLocal() as db:
        usuario = repo_usuarios.buscar_por_email(db, email.strip().lower())
        correcta = usuario is not None and len(password.encode()) <= MAX_BYTES_PASSWORD and bcrypt.checkpw(
            password.encode(), usuario.password_hash.encode()
        )
        if not correcta:
            raise HTTPException(401, "Email o contraseña incorrectos.")
        if usuario.estado != "activo":
            raise HTTPException(403, "Tu cuenta está suspendida.")
        ahora = ahora_utc()
        repo_usuarios.borrar_sesiones_vencidas(db, usuario.id, ahora)
        token = secrets.token_hex(32)
        expira_en = ahora + timedelta(days=config.DIAS_SESION)
        repo_usuarios.crear_sesion(db, usuario.id, token, expira_en)
        db.commit()
    return {"token": token, "expira_en": f"{expira_en.isoformat()}Z", "nombre": usuario.nombre}


def logout(token: str) -> None:
    """Borra la sesión de ese token."""
    with SessionLocal() as db:
        repo_usuarios.borrar_sesion(db, token)
        db.commit()


def usuario_por_token(token: str) -> Usuario:
    """Devuelve el dueño del token, o 401 si no sirve."""
    with SessionLocal() as db:
        sesion = repo_usuarios.buscar_sesion(db, token)
        if sesion is None or sesion.expira_en <= ahora_utc():
            raise HTTPException(401, "Tu sesión no es válida. Inicia sesión de nuevo.")
        usuario = repo_usuarios.buscar_por_id(db, sesion.usuario_id)
    if usuario.estado != "activo":
        raise HTTPException(403, "Tu cuenta está suspendida.")
    return usuario
