"""Consultas de usuarios y sesiones."""
from datetime import datetime
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models.tablas import Sesion, Usuario


def buscar_por_email(db: Session, email: str) -> Optional[Usuario]:
    """Busca un usuario por su email."""
    return db.scalar(select(Usuario).where(Usuario.email == email))


def buscar_por_id(db: Session, usuario_id: int) -> Optional[Usuario]:
    """Busca un usuario por su id."""
    return db.get(Usuario, usuario_id)


def crear(db: Session, email: str, nombre: str, password_hash: str) -> Usuario:
    """Agrega un usuario; quien llama hace el commit."""
    usuario = Usuario(email=email, nombre=nombre, password_hash=password_hash)
    db.add(usuario)
    db.flush()  # para que ya tenga id
    return usuario


def crear_sesion(db: Session, usuario_id: int, token: str, expira_en: datetime) -> Sesion:
    """Agrega una sesión; quien llama hace el commit."""
    sesion = Sesion(usuario_id=usuario_id, token=token, expira_en=expira_en)
    db.add(sesion)
    return sesion


def buscar_sesion(db: Session, token: str) -> Optional[Sesion]:
    """Busca una sesión por su token."""
    return db.scalar(select(Sesion).where(Sesion.token == token))


def borrar_sesion(db: Session, token: str) -> None:
    """Borra la sesión de ese token."""
    db.execute(delete(Sesion).where(Sesion.token == token))


def borrar_sesiones_vencidas(db: Session, usuario_id: int, ahora: datetime) -> None:
    """Borra las sesiones ya vencidas del usuario."""
    db.execute(delete(Sesion).where(Sesion.usuario_id == usuario_id, Sesion.expira_en < ahora))
