"""Un grafo por carpeta raíz: código único por (grafo, código).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# El grafo es la primera carpeta de la ruta relativa; los archivos sueltos quedan en "".
_GRAPH_FROM_PATH = (
    "CASE WHEN instr(file_path, '/') > 0 "
    "THEN substr(file_path, 1, instr(file_path, '/') - 1) ELSE '' END"
)


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("graph_name", sa.String(length=255), nullable=True))
    op.execute(f"UPDATE documents SET graph_name = {_GRAPH_FROM_PATH}")
    with op.batch_alter_table("documents") as batch:
        batch.alter_column("graph_name", existing_type=sa.String(length=255), nullable=False)
        batch.drop_index("ix_documents_code")
        batch.create_index("ix_documents_code", ["code"])
        batch.create_index("ix_documents_graph_name", ["graph_name"])
        batch.create_unique_constraint("uq_documents_graph_name_code", ["graph_name", "code"])

    with op.batch_alter_table("ingestion_runs") as batch:
        batch.add_column(
            sa.Column("root_files_count", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("ingestion_runs") as batch:
        batch.drop_column("root_files_count")
    with op.batch_alter_table("documents") as batch:
        batch.drop_constraint("uq_documents_graph_name_code", type_="unique")
        batch.drop_index("ix_documents_graph_name")
        batch.drop_index("ix_documents_code")
        batch.create_index("ix_documents_code", ["code"], unique=True)
        batch.drop_column("graph_name")
