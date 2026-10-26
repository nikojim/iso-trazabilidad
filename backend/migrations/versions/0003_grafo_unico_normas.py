"""Grafo único: la carpeta raíz pasa a ser la norma; planillas XLSX; contadores y log por corrida.

- ``documents.graph_name`` -> ``documents.norma`` (sigue ``UNIQUE(norma, code)``).
- ``file_format`` admite ``xlsx`` y ``extraction_status`` admite ``not_applicable``.
- Las referencias se re-resuelven en todo el grafo: primero en la norma del origen; si no
  existe allí, en la única otra norma que tenga el código; si hay varias, queda pendiente.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = (
    "ok",
    "no_references",
    "no_section",
    "needs_review",
    "requires_ocr",
    "error",
    "source_code_unresolved",
)
_RUN_COUNTERS = (
    "references_count",
    "occurrences_count",
    "duplicate_references_count",
    "unresolved_count",
)

# Misma regla que app.services.resolution.choose_target.
_RERESOLVE = """
UPDATE document_references SET target_document_id = (
    SELECT COALESCE(
        (SELECT d.id FROM documents d
          WHERE d.code = document_references.target_code AND d.is_active = 1
            AND d.norma = s.norma),
        (SELECT CASE WHEN COUNT(*) = 1 THEN MIN(d.id) END FROM documents d
          WHERE d.code = document_references.target_code AND d.is_active = 1
            AND d.norma <> s.norma)
    )
    FROM documents s WHERE s.id = document_references.source_document_id
)
"""


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=32)


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.drop_constraint("uq_documents_graph_name_code", type_="unique")
        batch.drop_index("ix_documents_graph_name")
        batch.alter_column(
            "graph_name", new_column_name="norma", existing_type=sa.String(length=255)
        )
        batch.alter_column(
            "file_format",
            existing_type=_enum("file_format", "pdf", "docx"),
            type_=_enum("file_format", "pdf", "docx", "xlsx"),
            existing_nullable=False,
        )
        batch.alter_column(
            "extraction_status",
            existing_type=_enum("extraction_status", *_STATUSES),
            type_=_enum("extraction_status", *_STATUSES, "not_applicable"),
            existing_nullable=False,
        )
    with op.batch_alter_table("documents") as batch:
        batch.create_index("ix_documents_norma", ["norma"])
        batch.create_unique_constraint("uq_documents_norma_code", ["norma", "code"])

    with op.batch_alter_table("ingestion_runs") as batch:
        for name in _RUN_COUNTERS:
            batch.add_column(sa.Column(name, sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("log_path", sa.String(length=1024), nullable=True))

    op.execute(_RERESOLVE)


def downgrade() -> None:
    connection = op.get_bind()
    new_values = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM documents "
            "WHERE file_format = 'xlsx' OR extraction_status = 'not_applicable'"
        )
    ).scalar()
    if new_values:
        raise RuntimeError(
            "Hay planillas XLSX en la base: borrarlas antes de volver a la revisión 0002"
        )

    with op.batch_alter_table("ingestion_runs") as batch:
        batch.drop_column("log_path")
        for name in reversed(_RUN_COUNTERS):
            batch.drop_column(name)

    with op.batch_alter_table("documents") as batch:
        batch.drop_constraint("uq_documents_norma_code", type_="unique")
        batch.drop_index("ix_documents_norma")
        batch.alter_column(
            "norma", new_column_name="graph_name", existing_type=sa.String(length=255)
        )
        batch.alter_column(
            "file_format",
            existing_type=_enum("file_format", "pdf", "docx", "xlsx"),
            type_=_enum("file_format", "pdf", "docx"),
            existing_nullable=False,
        )
        batch.alter_column(
            "extraction_status",
            existing_type=_enum("extraction_status", *_STATUSES, "not_applicable"),
            type_=_enum("extraction_status", *_STATUSES),
            existing_nullable=False,
        )
    with op.batch_alter_table("documents") as batch:
        batch.create_index("ix_documents_graph_name", ["graph_name"])
        batch.create_unique_constraint("uq_documents_graph_name_code", ["graph_name", "code"])
    # En 0002 cada carpeta era un grafo: las referencias entre carpetas vuelven a quedar pendientes.
    op.execute(
        "UPDATE document_references SET target_document_id = NULL WHERE target_document_id IN ("
        " SELECT t.id FROM documents t JOIN documents s"
        " ON s.id = document_references.source_document_id WHERE t.graph_name <> s.graph_name)"
    )
