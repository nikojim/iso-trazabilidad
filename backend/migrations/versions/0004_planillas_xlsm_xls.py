"""Planillas XLSM y XLS: ``file_format`` admite ``xlsm`` y ``xls``.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FORMATS = ("pdf", "docx", "xlsx")


def _enum(*values: str) -> sa.Enum:
    return sa.Enum(
        *values, name="file_format", native_enum=False, create_constraint=True, length=32
    )


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.alter_column(
            "file_format",
            existing_type=_enum(*_FORMATS),
            type_=_enum(*_FORMATS, "xlsm", "xls"),
            existing_nullable=False,
        )


def downgrade() -> None:
    count = (
        op.get_bind()
        .execute(sa.text("SELECT COUNT(*) FROM documents WHERE file_format IN ('xlsm', 'xls')"))
        .scalar()
    )
    if count:
        raise RuntimeError(
            "Hay planillas XLSM o XLS en la base: borrarlas antes de volver a la revisión 0003"
        )
    with op.batch_alter_table("documents") as batch:
        batch.alter_column(
            "file_format",
            existing_type=_enum(*_FORMATS, "xlsm", "xls"),
            type_=_enum(*_FORMATS),
            existing_nullable=False,
        )
