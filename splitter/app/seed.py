"""Prepara la base al arrancar: migraciones, planes y cuenta de administrador."""
import logging

import bcrypt
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from . import config
from .database import SessionLocal, ahora_utc, db_engine
from .repositories import suscripciones as repo_suscripciones
from .repositories import usuarios as repo_usuarios
from .services.cuotas import fin_de_periodo

log = logging.getLogger("splitter.seed")

# trabajos_por_mes: audios por periodo de 30 días. 0 = ilimitados.
PLANES = [
    {"nombre": "gratis", "precio_mensual": 0, "trabajos_por_mes": 15, "minutos_max_audio": 5, "mejor_calidad": False},
    {"nombre": "pro", "precio_mensual": 99, "trabajos_por_mes": 0, "minutos_max_audio": 20, "mejor_calidad": True},
    # Solo para la cuenta de administrador
    {"nombre": "admin", "precio_mensual": 0, "trabajos_por_mes": 0, "minutos_max_audio": 120, "mejor_calidad": True},
]


def migrar(motor=db_engine, hasta: str = "head") -> None:
    """Aplica las migraciones de migraciones/versions que falten (hasta "head" o esa versión)."""
    ajustes = Config(str(config.BASE_DIR / "alembic.ini"))
    ajustes.set_main_option("script_location", str(config.BASE_DIR / "migraciones"))
    tablas = set(inspect(motor).get_table_names())
    with motor.begin() as conexion:
        ajustes.attributes["conexion"] = conexion
        if "alembic_version" not in tablas and "usuarios" in tablas:
            # Base creada antes de usar Alembic: ya tiene las tablas iniciales
            log.info("Base sin historial de migraciones: se marca como 0001")
            command.stamp(ajustes, "0001")
        command.upgrade(ajustes, hasta)


def _preparar_planes() -> None:
    """Crea los planes que falten y deja los existentes igual que PLANES."""
    with SessionLocal() as db:
        for datos in PLANES:
            plan = repo_suscripciones.buscar_plan(db, datos["nombre"])
            if plan is None:
                repo_suscripciones.crear_plan(db, **datos)
                continue
            for campo, valor in datos.items():
                if getattr(plan, campo) != valor:
                    log.info("Plan %s: %s %s -> %s", plan.nombre, campo, getattr(plan, campo), valor)
                    setattr(plan, campo, valor)
        db.commit()


def preparar_base() -> None:
    """Crea lo que falte, sin duplicar."""
    migrar()
    _preparar_planes()
    preparar_admin()


def preparar_admin() -> None:
    _preparar_admin(config.ADMIN_EMAIL, config.ADMIN_PASSWORD, config.ADMIN_NOMBRE)
    _preparar_admin(config.ADMIN2_EMAIL, config.ADMIN2_PASSWORD, config.ADMIN2_NOMBRE)


def _preparar_admin(email: str, password: str, nombre: str) -> None:
    """Crea o actualiza una cuenta de administrador."""
    if not email or not password:
        return
    if len(password) < 8 or len(password.encode()) > 72:
        log.warning("SPLITTER_ADMIN_PASSWORD debe tener entre 8 y 72 caracteres; no se creó la cuenta de administrador %s", email)
        return
    with SessionLocal() as db:
        usuario = repo_usuarios.buscar_por_email(db, email)
        if usuario is None:
            hash_ = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            usuario = repo_usuarios.crear(db, email, nombre, hash_)
        elif not bcrypt.checkpw(password.encode(), usuario.password_hash.encode()):
            usuario.password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        usuario.estado = "activo"
        usuario.email_verificado = True
        activa = repo_suscripciones.buscar_activa(db, usuario.id)
        if activa is None or activa.plan.nombre != "admin" or activa.fin_periodo <= ahora_utc():
            if activa is not None:
                activa.estado = "cancelada"
                db.flush()
            plan = repo_suscripciones.buscar_plan(db, "admin")
            inicio = ahora_utc()
            repo_suscripciones.crear_suscripcion(db, usuario.id, plan, inicio, fin_de_periodo(inicio))
        db.commit()
    log.info("Cuenta de administrador lista: %s", email)
