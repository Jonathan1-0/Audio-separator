"""Las migraciones crean la misma base que describen los modelos, y una base de antes
de Alembic (como la de producción) se actualiza sin perder datos."""
import tempfile
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.database import Base
from app.seed import migrar


def _motor():
    ruta = Path(tempfile.mkdtemp()) / "m.db"
    return create_engine(f"sqlite:///{ruta}")


def test_base_nueva_igual_a_los_modelos():
    motor = _motor()
    migrar(motor)
    with motor.connect() as conexion:
        diferencias = compare_metadata(MigrationContext.configure(conexion), Base.metadata)
    assert diferencias == []


def test_base_de_antes_de_alembic_se_actualiza():
    motor = _motor()
    # Así quedaba una base creada con create_all antes de Alembic: las 8 tablas, sin alembic_version
    migrar(motor, "0001")
    with motor.begin() as c:
        c.execute(text("DROP TABLE alembic_version"))
        c.execute(text("INSERT INTO usuarios (email, nombre, password_hash, estado, creado_en) "
                       "VALUES ('viejo@ejemplo.com', 'Viejo', 'x', 'activo', '2026-01-01')"))
    migrar(motor)
    columnas = {c["name"] for c in inspect(motor).get_columns("usuarios")}
    assert {"telefono", "foto", "proveedor", "email_verificado", "totp_activo", "google_id"} <= columnas
    with motor.connect() as c:
        fila = c.execute(text("SELECT email, proveedor, email_verificado, totp_activo FROM usuarios")).one()
        version = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert tuple(fila) == ("viejo@ejemplo.com", "email", 0, 0)
    assert version == "0006"


def test_con_las_columnas_de_perfil_ya_puestas():
    """Como Aiven: ya tenía telefono/foto/proveedor (agregadas al arrancar) pero no alembic_version."""
    motor = _motor()
    migrar(motor, "0002")
    with motor.begin() as c:
        c.execute(text("DROP TABLE alembic_version"))
    migrar(motor)
    assert "email_verificado" in {c["name"] for c in inspect(motor).get_columns("usuarios")}
    assert "cancelar_al_final" in {c["name"] for c in inspect(motor).get_columns("suscripciones")}


def test_migrar_una_base_con_datos():
    """Con filas que apuntan a usuarios (sesiones, suscripciones), las migraciones no deben fallar."""
    motor = _motor()
    migrar(motor, "0003")
    with motor.begin() as c:
        c.execute(text("PRAGMA foreign_keys=ON"))
        c.execute(text("INSERT INTO usuarios (id, email, nombre, password_hash, estado, creado_en, proveedor, email_verificado) "
                       "VALUES (1, 'a@ejemplo.com', 'A', 'x', 'activo', '2026-01-01', 'email', 0)"))
        c.execute(text("INSERT INTO sesiones (usuario_id, token, expira_en, creado_en) VALUES (1, 't', '2027-01-01', '2026-01-01')"))
        c.execute(text("INSERT INTO planes (id, nombre, precio_mensual, trabajos_por_mes, minutos_max_audio, mejor_calidad) "
                       "VALUES (1, 'gratis', 0, 5, 5, 0)"))
        c.execute(text("INSERT INTO suscripciones (usuario_id, plan_id, estado, inicio_periodo, fin_periodo) "
                       "VALUES (1, 1, 'activa', '2026-01-01', '2026-02-01')"))
    migrar(motor)
    with motor.connect() as c:
        assert c.execute(text("SELECT count(*) FROM sesiones")).scalar() == 1
        assert c.execute(text("SELECT totp_activo, google_id, tiene_password FROM usuarios")).one() == (0, None, 1)


def test_cuentas_de_google_quedan_sin_contrasena_propia():
    motor = _motor()
    migrar(motor, "0004")
    with motor.begin() as c:
        for i, proveedor in enumerate(("email", "google", "facebook"), start=1):
            c.execute(text("INSERT INTO usuarios (id, email, nombre, password_hash, estado, creado_en, proveedor) "
                           f"VALUES ({i}, '{proveedor}@ejemplo.com', 'X', 'x', 'activo', '2026-01-01', '{proveedor}')"))
    migrar(motor)
    with motor.connect() as c:
        filas = dict(c.execute(text("SELECT proveedor, tiene_password FROM usuarios")).all())
    assert filas == {"email": 1, "google": 0, "facebook": 0}
