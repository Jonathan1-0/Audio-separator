"""Correo confirmado.

Revisión: 0003
Anterior: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existentes = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("usuarios")}
    if "email_verificado" not in existentes:
        with op.batch_alter_table("usuarios") as tabla:
            tabla.add_column(sa.Column("email_verificado", sa.Boolean, nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("usuarios") as tabla:
        tabla.drop_column("email_verificado")
