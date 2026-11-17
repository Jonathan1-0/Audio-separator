"""Perfil: teléfono, foto y cómo se creó la cuenta.

Revisión: 0002
Anterior: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _columnas(tabla: str) -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(tabla)}


def upgrade() -> None:
    # Antes de Alembic estas columnas se agregaban al arrancar: si ya están, no se tocan
    existentes = _columnas("usuarios")
    with op.batch_alter_table("usuarios") as tabla:
        if "telefono" not in existentes:
            tabla.add_column(sa.Column("telefono", sa.String(20)))
        if "foto" not in existentes:
            tabla.add_column(sa.Column("foto", sa.String(64)))
        if "proveedor" not in existentes:
            tabla.add_column(sa.Column("proveedor", sa.String(20), nullable=False, server_default="email"))


def downgrade() -> None:
    with op.batch_alter_table("usuarios") as tabla:
        for columna in ("proveedor", "foto", "telefono"):
            tabla.drop_column(columna)
