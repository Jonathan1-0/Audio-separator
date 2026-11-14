"""Consultas de usuarios y sesiones."""
from datetime import datetime
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models.tablas import Sesion, Usuario


def buscar_por_email(db: Session, email: str) -> Optional[Usuario]:
    return db.scalar(select(Usuario).where(Usuario.email == email))


def buscar_por_id(db: Session, usuario_id: int) -> Optional[Usuario]:
    return db.get(Usuario, usuario_id)


def crear(db: Session, email: str, nombre: str, password_hash: str) -> Usuario:
    usuario = Usuario(email=email, nombre=nombre, password_hash=password_hash)
    db.add(usuario)
    db.flush()
    return usuario


def crear_sesion(db: Session, usuario_id: int, token: str, expira_en: datetime) -> Sesion:
    sesion = Sesion(usuario_id=usuario_id, token=token, expira_en=expira_en)
    db.add(sesion)
    return sesion


def buscar_sesion(db: Session, token: str) -> Optional[Sesion]:
    return db.scalar(select(Sesion).where(Sesion.token == token))


def borrar_sesion(db: Session, token: str) -> None:
    db.execute(delete(Sesion).where(Sesion.token == token))


def borrar_sesiones_vencidas(db: Session, usuario_id: int, ahora: datetime) -> None:
    db.execute(delete(Sesion).where(Sesion.usuario_id == usuario_id, Sesion.expira_en < ahora))


def cambiar_password(db: Session, usuario: Usuario, password_hash: str) -> None:
    usuario.password_hash = password_hash
    db.add(usuario)


def borrar_sesiones_de(db: Session, usuario_id: int) -> None:
    """Cierra todas las sesiones del usuario."""
    db.execute(delete(Sesion).where(Sesion.usuario_id == usuario_id))
