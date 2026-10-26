"""Esquema inicial de ISO Trace.

Revision ID: 0001
Revises:
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=32)


def upgrade() -> None:
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mode", _enum("mode", "full", "incremental", "single"), nullable=False),
        sa.Column("root_path", sa.String(length=1024), nullable=False),
        sa.Column(
            "status",
            _enum(
                "status", "running", "completed", "completed_with_errors", "failed", "interrupted"
            ),
            nullable=False,
        ),
        sa.Column("processed_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("new_count", sa.Integer(), nullable=False),
        sa.Column("updated_count", sa.Integer(), nullable=False),
        sa.Column("missing_count", sa.Integer(), nullable=False),
        sa.Column("no_section_count", sa.Integer(), nullable=False),
        sa.Column("unsupported_skipped_count", sa.Integer(), nullable=False),
        sa.Column("options_json", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_runs")),
    )
    op.create_index(op.f("ix_ingestion_runs_status"), "ingestion_runs", ["status"])

    meta = op.create_table(
        "meta",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_meta")),
    )
    op.bulk_insert(meta, [{"key": "graph_version", "value": "0"}])

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("document_type", sa.String(length=8), nullable=False),
        sa.Column("system_code", sa.String(length=8), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("version", sa.String(length=16), nullable=True),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("folder", sa.String(length=1024), nullable=False),
        sa.Column("file_format", _enum("file_format", "pdf", "docx"), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("file_mtime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("references_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "extraction_status",
            _enum(
                "extraction_status",
                "ok",
                "no_references",
                "no_section",
                "needs_review",
                "requires_ocr",
                "error",
                "source_code_unresolved",
            ),
            nullable=False,
        ),
        sa.Column(
            "code_source",
            _enum("code_source", "filename", "content", "filename+content", "override"),
            nullable=True,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("last_run_id", sa.Integer(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["last_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_documents_last_run_id_ingestion_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("file_path", name=op.f("uq_documents_file_path")),
    )
    op.create_index(op.f("ix_documents_code"), "documents", ["code"], unique=True)
    op.create_index(op.f("ix_documents_document_type"), "documents", ["document_type"])
    op.create_index(op.f("ix_documents_system_code"), "documents", ["system_code"])
    op.create_index(op.f("ix_documents_title"), "documents", ["title"])

    op.create_table(
        "document_references",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_document_id", sa.Integer(), nullable=False),
        sa.Column("target_code", sa.String(length=32), nullable=False),
        sa.Column("target_document_id", sa.Integer(), nullable=True),
        sa.Column("group_name", sa.String(length=32), nullable=False),
        sa.Column("has_mixed_groups", sa.Boolean(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("target_title_hint", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "occurrence_count >= 1",
            name=op.f("ck_document_references_occurrence_count_positive"),
        ),
        sa.CheckConstraint(
            "target_code = upper(target_code)",
            name=op.f("ck_document_references_target_code_upper"),
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["documents.id"],
            name=op.f("fk_document_references_source_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_document_id"],
            ["documents.id"],
            name=op.f("fk_document_references_target_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_references")),
        sa.UniqueConstraint(
            "source_document_id",
            "target_code",
            name=op.f("uq_document_references_source_document_id_target_code"),
        ),
    )
    op.create_index(
        op.f("ix_document_references_target_code"), "document_references", ["target_code"]
    )
    op.create_index(
        op.f("ix_document_references_target_document_id"),
        "document_references",
        ["target_document_id"],
    )

    op.create_table(
        "quality_issues",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("file_path", sa.String(length=1024), nullable=True),
        sa.Column("code", sa.String(length=32), nullable=True),
        sa.Column("issue_type", sa.String(length=64), nullable=False),
        sa.Column("severity", _enum("severity", "info", "warning", "error"), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_quality_issues_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_quality_issues_run_id_ingestion_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quality_issues")),
    )
    op.create_index(op.f("ix_quality_issues_document_id"), "quality_issues", ["document_id"])
    op.create_index("ix_quality_issues_type_open", "quality_issues", ["issue_type", "resolved_at"])

    op.create_table(
        "reference_occurrences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reference_id", sa.Integer(), nullable=False),
        sa.Column("group_name", sa.String(length=32), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("paragraph_index", sa.Integer(), nullable=True),
        sa.Column("table_index", sa.Integer(), nullable=True),
        sa.Column("row_index", sa.Integer(), nullable=True),
        sa.Column("cell_index", sa.Integer(), nullable=True),
        sa.Column("raw_text", sa.String(length=200), nullable=False),
        sa.Column("evidence_excerpt", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "page_number IS NULL OR page_number >= 1",
            name=op.f("ck_reference_occurrences_page_number_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["reference_id"],
            ["document_references.id"],
            name=op.f("fk_reference_occurrences_reference_id_document_references"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reference_occurrences")),
    )
    op.create_index(
        op.f("ix_reference_occurrences_reference_id"), "reference_occurrences", ["reference_id"]
    )


def downgrade() -> None:
    op.drop_table("reference_occurrences")
    op.drop_table("quality_issues")
    op.drop_table("document_references")
    op.drop_table("documents")
    op.drop_table("meta")
    op.drop_table("ingestion_runs")
