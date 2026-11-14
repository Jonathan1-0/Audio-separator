"""Prepara la base al arrancar: tablas, planes y la cuenta de administrador (si está en .env)."""
import logging
from datetime import timedelta

import bcrypt

from . import config
from .database import Base, SessionLocal, ahora_utc, db_engine
from .models import tablas  # noqa: F401 - registra las tablas en Base
from .repositories import suscripciones as repo_suscripciones
from .repositories import usuarios as repo_usuarios

log = logging.getLogger("splitter.seed")

PLANES = [
    {"nombre": "gratis", "precio_mensual": 0, "trabajos_por_mes": 5, "minutos_max_audio": 5, "mejor_calidad": False},
    {"nombre": "pro", "precio_mensual": 99, "trabajos_por_mes": 100, "minutos_max_audio": 20, "mejor_calidad": True},
    # Solo para la cuenta de administrador; no se vende ni sale en la página de planes.
    {"nombre": "admin", "precio_mensual": 0, "trabajos_por_mes": 100000, "minutos_max_audio": 120, "mejor_calidad": True},
]


def preparar_base() -> None:
    """Crea lo que falte, sin duplicar."""
    Base.metadata.create_all(db_engine)
    with SessionLocal() as db:
        for datos in PLANES:
            if repo_suscripciones.buscar_plan(db, datos["nombre"]) is None:
                repo_suscripciones.crear_plan(db, **datos)
        db.commit()
    preparar_admin()


def preparar_admin() -> None:
    """Crea la cuenta de administrador o la pone al día: contraseña de .env y plan admin activo."""
    email, password = config.ADMIN_EMAIL, config.ADMIN_PASSWORD
    if not email or not password:
        return
    # Las mismas reglas que una cuenta normal (services/auth.py).
    if len(password) < 8 or len(password.encode()) > 72:
        log.warning("SPLITTER_ADMIN_PASSWORD debe tener entre 8 y 72 caracteres; no se creó la cuenta de administrador")
        return
    with SessionLocal() as db:
        usuario = repo_usuarios.buscar_por_email(db, email)
        if usuario is None:
            hash_ = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            usuario = repo_usuarios.crear(db, email, config.ADMIN_NOMBRE, hash_)
        elif not bcrypt.checkpw(password.encode(), usuario.password_hash.encode()):
            usuario.password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        usuario.estado = "activo"
        activa = repo_suscripciones.buscar_activa(db, usuario.id)
        if activa is None or activa.plan.nombre != "admin" or activa.fin_periodo <= ahora_utc():
            if activa is not None:
                activa.estado = "cancelada"
                db.flush()
            plan = repo_suscripciones.buscar_plan(db, "admin")
            inicio = ahora_utc()
            repo_suscripciones.crear_suscripcion(db, usuario.id, plan, inicio, inicio + timedelta(days=config.DIAS_PERIODO))
        db.commit()
    log.info("Cuenta de administrador lista: %s", email)
