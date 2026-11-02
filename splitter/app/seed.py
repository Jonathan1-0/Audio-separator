"""Prepara la base al arrancar: tablas y planes."""
from .database import Base, SessionLocal, db_engine
from .models import tablas  # noqa: F401 - registra las tablas en Base
from .repositories import suscripciones as repo_suscripciones

PLANES = [
    {"nombre": "gratis", "precio_mensual": 0, "trabajos_por_mes": 5, "minutos_max_audio": 5, "mejor_calidad": False},
    {"nombre": "pro", "precio_mensual": 99, "trabajos_por_mes": 100, "minutos_max_audio": 20, "mejor_calidad": True},
]


def preparar_base() -> None:
    """Crea las tablas que falten y los planes, sin duplicar lo que ya existe."""
    Base.metadata.create_all(db_engine)
    with SessionLocal() as db:
        for datos in PLANES:
            if repo_suscripciones.buscar_plan(db, datos["nombre"]) is None:
                repo_suscripciones.crear_plan(db, **datos)
        db.commit()
