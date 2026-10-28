"""Huella de extracción: ``documents.extraction_fingerprint``.

Los documentos existentes quedan con NULL, así que la próxima ingesta incremental los
vuelve a procesar una vez con las reglas actuales.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("extraction_fingerprint", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("extraction_fingerprint")
