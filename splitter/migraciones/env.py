"""Alembic usa la misma conexión que la app (DATABASE_URL de .env)."""
from alembic import context

from app.database import Base, db_engine
from app.models import tablas  # noqa: F401  registra las tablas en Base.metadata

objetivo = Base.metadata


def correr() -> None:
    conexion = context.config.attributes.get("conexion")
    if conexion is not None:  # la app pasa su propia conexión
        context.configure(connection=conexion, target_metadata=objetivo, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    with db_engine.connect() as conexion:
        context.configure(connection=conexion, target_metadata=objetivo, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("Las migraciones se corren contra la base (sin --sql).")
correr()
