"""Facebook conectado y si la cuenta tiene contraseña propia.

Revisión: 0005
Anterior: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("usuarios", sa.Column("facebook_id", sa.String(64)))
    op.create_index("ix_usuarios_facebook_id", "usuarios", ["facebook_id"], unique=True)
    op.add_column("usuarios", sa.Column("tiene_password", sa.Boolean, nullable=False, server_default=sa.true()))
    # Las cuentas creadas con Google o Facebook tienen una contraseña al azar que nadie conoce
    op.execute("UPDATE usuarios SET tiene_password = 0 WHERE proveedor IN ('google', 'facebook')")


def downgrade() -> None:
    op.drop_index("ix_usuarios_facebook_id", table_name="usuarios")
    with op.batch_alter_table("usuarios") as tabla:
        tabla.drop_column("tiene_password")
        tabla.drop_column("facebook_id")
