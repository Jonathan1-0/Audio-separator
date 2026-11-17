"""Verificación en dos pasos, Google conectado y cancelar Pro al final del periodo.

Revisión: 0004
Anterior: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


# Sin batch_alter_table: agregar columnas e índices no obliga a reconstruir la tabla
# (reconstruirla falla en SQLite si otras tablas ya apuntan a sus filas).
def upgrade() -> None:
    op.add_column("usuarios", sa.Column("totp_secreto", sa.String(64)))
    op.add_column("usuarios", sa.Column("totp_activo", sa.Boolean, nullable=False, server_default=sa.false()))
    op.add_column("usuarios", sa.Column("totp_respaldo", sa.Text))
    op.add_column("usuarios", sa.Column("google_id", sa.String(64)))
    op.create_index("ix_usuarios_google_id", "usuarios", ["google_id"], unique=True)
    op.add_column("suscripciones", sa.Column("cancelar_al_final", sa.Boolean, nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("suscripciones") as tabla:
        tabla.drop_column("cancelar_al_final")
    op.drop_index("ix_usuarios_google_id", table_name="usuarios")
    with op.batch_alter_table("usuarios") as tabla:
        for columna in ("google_id", "totp_respaldo", "totp_activo", "totp_secreto"):
            tabla.drop_column(columna)
