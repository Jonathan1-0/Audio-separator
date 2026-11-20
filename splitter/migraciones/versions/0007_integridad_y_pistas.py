"""Calidad de la base: 1FN en las pistas pedidas, CHECK en estados y valores, y ON DELETE CASCADE.

- trabajos.pistas_pedidas ("vocals,drums") pasa a la tabla trabajo_pistas, una fila por pista.
- Los estados, presets y proveedores solo aceptan los valores que usa la app; los montos y
  contadores no pueden ser negativos y el progreso va de 0 a 100.
- Borrar un trabajo borra sus resultados y pistas, y borrar un usuario borra sus sesiones y
  trabajos. Suscripciones, métodos de pago y pagos NO se borran en cascada: son el historial
  de cobros y la base impide borrar a un usuario que los tenga.

En MySQL los ALTER no van dentro de una transacción, así que el orden importa: primero se
copian las pistas a la tabla nueva y al final se quita la columna vieja.

Revisión: 0007
Anterior: 0006
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

# En SQLite las llaves foráneas no tienen nombre: así se les pone uno para poder cambiarlas
NOMBRES = {"fk": "fk_%(table_name)s_%(column_0_name)s"}

CHECKS = {
    "usuarios": {
        "ck_usuarios_estado": "estado IN ('pendiente', 'activo', 'suspendido', 'borrada')",
        "ck_usuarios_proveedor": "proveedor IN ('email', 'google', 'facebook')",
    },
    "planes": {
        "ck_planes_precio": "precio_mensual >= 0",
        "ck_planes_trabajos": "trabajos_por_mes >= 0",
        "ck_planes_minutos": "minutos_max_audio > 0",
    },
    "suscripciones": {
        "ck_suscripciones_estado": "estado IN ('activa', 'cancelada', 'vencida')",
        "ck_suscripciones_periodo": "fin_periodo > inicio_periodo",
    },
    "pagos": {
        "ck_pagos_estado": "estado IN ('pagado', 'fallido')",
        "ck_pagos_monto": "monto >= 0",
    },
    "trabajos": {
        "ck_trabajos_estado": "estado IN ('en_cola', 'procesando', 'completado', 'error')",
        "ck_trabajos_preset": "preset IN ('2stem', '4stem', '4stem_fast', 'denoise')",
        "ck_trabajos_progreso": "progreso BETWEEN 0 AND 100",
        "ck_trabajos_tamano": "tamano_bytes >= 0",
    },
}

# (tabla, columna, tabla a la que apunta): pasan a ON DELETE CASCADE
CASCADAS = [
    ("trabajos", "usuario_id", "usuarios"),
    ("sesiones", "usuario_id", "usuarios"),
    ("resultados", "trabajo_id", "trabajos"),
]


def _es_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _nombre_fk(tabla: str, columna: str) -> str:
    """Nombre real de la llave foránea (en MySQL, p. ej. sesiones_ibfk_1). En SQLite no tiene,
    y se usa el que le da NOMBRES dentro de batch_alter_table."""
    for fk in sa.inspect(op.get_bind()).get_foreign_keys(tabla):
        if fk["constrained_columns"] == [columna]:
            return fk["name"] or NOMBRES["fk"] % {"table_name": tabla, "column_0_name": columna}
    raise RuntimeError(f"No encontré la llave foránea {tabla}.{columna}")


def _cambiar_fk(lote, tabla: str, columna: str, destino: str, ondelete) -> None:
    lote.drop_constraint(_nombre_fk(tabla, columna), type_="foreignkey")
    lote.create_foreign_key(f"fk_{tabla}_{columna}", destino, [columna], ["id"], ondelete=ondelete)


def _crear_tabla_pistas(filas) -> None:
    op.create_table(
        "trabajo_pistas",
        sa.Column("trabajo_id", sa.String(32), sa.ForeignKey("trabajos.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("stem", sa.String(30), primary_key=True),
        sa.Column("orden", sa.Integer, nullable=False),
    )
    pistas = []
    for trabajo_id, texto in filas:
        vistas = set()
        for stem in (s.strip() for s in (texto or "").split(",")):
            if stem and stem not in vistas:  # una pista repetida rompería la llave primaria
                vistas.add(stem)
                pistas.append({"trabajo_id": trabajo_id, "stem": stem[:30], "orden": len(vistas) - 1})
    if pistas:
        tabla = sa.table("trabajo_pistas", sa.column("trabajo_id"), sa.column("stem"), sa.column("orden"))
        op.bulk_insert(tabla, pistas)


def upgrade() -> None:
    # En SQLite, migrar() apaga las llaves foráneas mientras se recrean las tablas
    sqlite = _es_sqlite()

    filas = op.get_bind().execute(sa.text("SELECT id, pistas_pedidas FROM trabajos")).all()
    if not sqlite:
        _crear_tabla_pistas(filas)

    for tabla, checks in CHECKS.items():
        with op.batch_alter_table(tabla, naming_convention=NOMBRES) as lote:
            for nombre, condicion in checks.items():
                lote.create_check_constraint(nombre, condicion)
            if tabla == "trabajos":
                _cambiar_fk(lote, "trabajos", "usuario_id", "usuarios", "CASCADE")
                lote.drop_column("pistas_pedidas")

    for tabla, columna, destino in CASCADAS[1:]:
        with op.batch_alter_table(tabla, naming_convention=NOMBRES) as lote:
            _cambiar_fk(lote, tabla, columna, destino, "CASCADE")

    if sqlite:
        # SQLite recrea trabajos para quitarle la columna; la tabla nueva se llena después
        _crear_tabla_pistas(filas)


def downgrade() -> None:
    bind = op.get_bind()
    pistas = {}
    for trabajo_id, stem in bind.execute(
        sa.text("SELECT trabajo_id, stem FROM trabajo_pistas ORDER BY trabajo_id, orden")
    ):
        pistas.setdefault(trabajo_id, []).append(stem)
    op.drop_table("trabajo_pistas")

    for tabla, columna, destino in reversed(CASCADAS[1:]):
        with op.batch_alter_table(tabla, naming_convention=NOMBRES) as lote:
            _cambiar_fk(lote, tabla, columna, destino, None)

    with op.batch_alter_table("trabajos", naming_convention=NOMBRES) as lote:
        lote.add_column(sa.Column("pistas_pedidas", sa.String(255), nullable=False, server_default=""))
    trabajos = sa.table("trabajos", sa.column("id"), sa.column("pistas_pedidas"))
    for trabajo_id, stems in pistas.items():
        bind.execute(trabajos.update().where(trabajos.c.id == trabajo_id).values(pistas_pedidas=",".join(stems)))

    for tabla, checks in reversed(CHECKS.items()):
        with op.batch_alter_table(tabla, naming_convention=NOMBRES) as lote:
            for nombre in checks:
                lote.drop_constraint(nombre, type_="check")
            if tabla == "trabajos":
                _cambiar_fk(lote, "trabajos", "usuario_id", "usuarios", None)
                lote.alter_column("pistas_pedidas", server_default=None)
