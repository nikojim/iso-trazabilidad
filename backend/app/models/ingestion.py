from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UtcDateTime, str_enum, utcnow
from app.models.enums import RunMode, RunStatus, Severity


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    mode: Mapped[RunMode] = mapped_column(str_enum(RunMode, "mode"))
    root_path: Mapped[str] = mapped_column(String(1024))
    status: Mapped[RunStatus] = mapped_column(
        str_enum(RunStatus, "status"), default=RunStatus.RUNNING, index=True
    )

    processed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    missing_count: Mapped[int] = mapped_column(Integer, default=0)
    no_section_count: Mapped[int] = mapped_column(Integer, default=0)
    unsupported_skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    # Archivos sueltos en la raíz: no pertenecen a ninguna norma y no se procesan.
    root_files_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Referencias de los documentos publicados en la corrida (relaciones lógicas y evidencias).
    references_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    occurrences_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    duplicate_references_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    unresolved_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    log_path: Mapped[str | None] = mapped_column(String(1024))

    options_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class QualityIssue(Base):
    """Incidencia detectada durante la ingesta (las derivadas se calculan, no se guardan)."""

    __tablename__ = "quality_issues"
    __table_args__ = (Index("ix_quality_issues_type_open", "issue_type", "resolved_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_runs.id", ondelete="SET NULL"))
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    file_path: Mapped[str | None] = mapped_column(String(1024))
    code: Mapped[str | None] = mapped_column(String(32))
    # Texto libre (no enum) para poder sumar tipos sin migrar el esquema.
    issue_type: Mapped[str] = mapped_column(String(64))
    severity: Mapped[Severity] = mapped_column(str_enum(Severity, "severity"))
    message: Mapped[str] = mapped_column(Text)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
