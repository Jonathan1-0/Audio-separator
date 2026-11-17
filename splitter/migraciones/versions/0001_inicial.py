"""Tablas iniciales (las 8 de antes de usar Alembic).

Revisión: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usuarios",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("nombre", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("estado", sa.String(20), nullable=False),
        sa.Column("creado_en", sa.DateTime, nullable=False),
    )
    op.create_table(
        "sesiones",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("usuario_id", sa.Integer, sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("token", sa.String(64), nullable=False, unique=True),
        sa.Column("expira_en", sa.DateTime, nullable=False),
        sa.Column("creado_en", sa.DateTime, nullable=False),
    )
    op.create_table(
        "planes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nombre", sa.String(20), nullable=False, unique=True),
        sa.Column("precio_mensual", sa.Numeric(10, 2), nullable=False),
        sa.Column("trabajos_por_mes", sa.Integer, nullable=False),
        sa.Column("minutos_max_audio", sa.Integer, nullable=False),
        sa.Column("mejor_calidad", sa.Boolean, nullable=False),
    )
    op.create_table(
        "suscripciones",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("usuario_id", sa.Integer, sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("plan_id", sa.Integer, sa.ForeignKey("planes.id"), nullable=False),
        sa.Column("estado", sa.String(20), nullable=False),
        sa.Column("inicio_periodo", sa.DateTime, nullable=False),
        sa.Column("fin_periodo", sa.DateTime, nullable=False),
    )
    op.create_table(
        "metodos_pago",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("usuario_id", sa.Integer, sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("marca", sa.String(30), nullable=False),
        sa.Column("ultimos4", sa.String(4), nullable=False),
        sa.Column("token_pasarela", sa.String(64), nullable=False),
    )
    op.create_table(
        "pagos",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("suscripcion_id", sa.Integer, sa.ForeignKey("suscripciones.id"), nullable=False),
        sa.Column("metodo_pago_id", sa.Integer, sa.ForeignKey("metodos_pago.id"), nullable=False),
        sa.Column("monto", sa.Numeric(10, 2), nullable=False),
        sa.Column("moneda", sa.String(3), nullable=False),
        sa.Column("estado", sa.String(20), nullable=False),
        sa.Column("id_transaccion", sa.String(64), nullable=False),
        sa.Column("fecha", sa.DateTime, nullable=False),
    )
    op.create_table(
        "trabajos",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("usuario_id", sa.Integer, sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("nombre_original", sa.String(255), nullable=False),
        sa.Column("tamano_bytes", sa.BigInteger, nullable=False),
        sa.Column("preset", sa.String(20), nullable=False),
        sa.Column("pistas_pedidas", sa.String(255), nullable=False),
        sa.Column("estado", sa.String(20), nullable=False),
        sa.Column("progreso", sa.Integer, nullable=False),
        sa.Column("duracion_audio_seg", sa.Float),
        sa.Column("gpu_seconds", sa.Float),
        sa.Column("mensaje_error", sa.String(500)),
        sa.Column("creado_en", sa.DateTime, nullable=False),
        sa.Column("terminado_en", sa.DateTime),
    )
    op.create_table(
        "resultados",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("trabajo_id", sa.String(32), sa.ForeignKey("trabajos.id"), nullable=False),
        sa.Column("stem", sa.String(30), nullable=False),
        sa.Column("ruta_archivo", sa.String(500), nullable=False),
        sa.Column("expira_en", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    for tabla in ("resultados", "trabajos", "pagos", "metodos_pago", "suscripciones", "planes", "sesiones", "usuarios"):
        op.drop_table(tabla)
