"""Conexión a la base de datos."""
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config

load_dotenv(config.BASE_DIR / ".env")

DATABASE_URL = os.getenv("DATABASE_URL") or "sqlite:///splitter.db"
ES_SQLITE = DATABASE_URL.startswith("sqlite")


def _argumentos_conexion() -> dict:
    if ES_SQLITE:
        # Los hilos de la cola y los de FastAPI comparten la base.
        return {"check_same_thread": False}
    ruta_ca = os.getenv("DB_SSL_CA")
    return {"ssl": {"ca": str(config.BASE_DIR / ruta_ca)}} if ruta_ca else {}


db_engine = create_engine(
    DATABASE_URL,
    connect_args=_argumentos_conexion(),
    pool_pre_ping=True,
    pool_recycle=280,
)

# expire_on_commit=False: los datos se pueden leer después de cerrar la sesión.
SessionLocal = sessionmaker(bind=db_engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


if ES_SQLITE:
    @event.listens_for(db_engine, "connect")
    def _activar_foreign_keys(conexion, _registro) -> None:
        # SQLite no revisa las llaves foráneas si no se le pide.
        cursor = conexion.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def ahora_utc() -> datetime:
    """Sin zona horaria porque DATETIME de MySQL no la guarda."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
