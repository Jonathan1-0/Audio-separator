"""Formato del archivo que se subió (mp3, wav...), para mostrarlo en «Mis audios».

Revisión: 0006
Anterior: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trabajos", sa.Column("formato", sa.String(10)))


def downgrade() -> None:
    with op.batch_alter_table("trabajos") as tabla:
        tabla.drop_column("formato")
