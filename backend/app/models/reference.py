from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UtcDateTime, utcnow

if TYPE_CHECKING:
    from app.models.document import Document


class DocumentReference(Base):
    """Relación lógica única ``origen -> target_code`` (el origen cita al destino)."""

    __tablename__ = "document_references"
    __table_args__ = (
        # También sirve como índice por source_document_id (columna inicial).
        UniqueConstraint("source_document_id", "target_code"),
        CheckConstraint("target_code = upper(target_code)", name="target_code_upper"),
        CheckConstraint("occurrence_count >= 1", name="occurrence_count_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    target_code: Mapped[str] = mapped_column(String(32), index=True)
    # NULL mientras el documento destino no esté incorporado.
    target_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    group_name: Mapped[str] = mapped_column(String(32))
    has_mixed_groups: Mapped[bool] = mapped_column(Boolean, default=False)
    occurrence_count: Mapped[int] = mapped_column(Integer)
    target_title_hint: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow, onupdate=utcnow)

    source_document: Mapped["Document"] = relationship(
        back_populates="outgoing_references", foreign_keys=[source_document_id]
    )
    target_document: Mapped["Document | None"] = relationship(
        back_populates="incoming_references", foreign_keys=[target_document_id]
    )
    occurrences: Mapped[list["ReferenceOccurrence"]] = relationship(
        back_populates="reference",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ReferenceOccurrence.ordinal",
    )


class ReferenceOccurrence(Base):
    """Evidencia de una aparición del código dentro de la sección REFERENCIAS."""

    __tablename__ = "reference_occurrences"
    __table_args__ = (
        CheckConstraint("page_number IS NULL OR page_number >= 1", name="page_number_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reference_id: Mapped[int] = mapped_column(
        ForeignKey("document_references.id", ondelete="CASCADE"), index=True
    )
    group_name: Mapped[str] = mapped_column(String(32))
    ordinal: Mapped[int] = mapped_column(Integer)
    page_number: Mapped[int | None] = mapped_column(Integer)
    paragraph_index: Mapped[int | None] = mapped_column(Integer)
    table_index: Mapped[int | None] = mapped_column(Integer)
    row_index: Mapped[int | None] = mapped_column(Integer)
    cell_index: Mapped[int | None] = mapped_column(Integer)
    raw_text: Mapped[str] = mapped_column(String(200))
    evidence_excerpt: Mapped[str | None] = mapped_column(Text)

    reference: Mapped[DocumentReference] = relationship(back_populates="occurrences")
