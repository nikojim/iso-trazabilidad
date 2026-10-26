from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UtcDateTime, str_enum, utcnow
from app.models.enums import CodeSource, ExtractionStatus, FileFormat

if TYPE_CHECKING:
    from app.models.reference import DocumentReference


class Document(Base):
    __tablename__ = "documents"
    # Un solo grafo; la carpeta raíz es la norma. El código es único dentro de la norma:
    # dos normas pueden tener documentos distintos con el mismo código.
    __table_args__ = (UniqueConstraint("norma", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    norma: Mapped[str] = mapped_column(String(255), index=True)
    code: Mapped[str] = mapped_column(String(32), index=True)
    document_type: Mapped[str] = mapped_column(String(8), index=True)
    system_code: Mapped[str] = mapped_column(String(8), index=True)
    title: Mapped[str | None] = mapped_column(String(500), index=True)
    version: Mapped[str | None] = mapped_column(String(16))

    file_path: Mapped[str] = mapped_column(String(1024), unique=True)
    folder: Mapped[str] = mapped_column(String(1024), default="")
    file_format: Mapped[FileFormat] = mapped_column(str_enum(FileFormat, "file_format"))
    file_size: Mapped[int] = mapped_column(Integer)
    file_mtime: Mapped[datetime] = mapped_column(UtcDateTime())
    sha256: Mapped[str] = mapped_column(String(64))
    references_sha256: Mapped[str | None] = mapped_column(String(64))

    extraction_status: Mapped[ExtractionStatus] = mapped_column(
        str_enum(ExtractionStatus, "extraction_status")
    )
    code_source: Mapped[CodeSource | None] = mapped_column(str_enum(CodeSource, "code_source"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    last_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="SET NULL")
    )
    first_seen_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    last_processed_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow, onupdate=utcnow)

    outgoing_references: Mapped[list["DocumentReference"]] = relationship(
        back_populates="source_document",
        foreign_keys="DocumentReference.source_document_id",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    incoming_references: Mapped[list["DocumentReference"]] = relationship(
        back_populates="target_document",
        foreign_keys="DocumentReference.target_document_id",
        passive_deletes=True,
    )

    @property
    def references_stale(self) -> bool:
        """Las referencias vigentes no corresponden al último contenido leído del archivo."""
        return self.references_sha256 is not None and self.references_sha256 != self.sha256
