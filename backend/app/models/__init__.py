"""Modelos ORM. Importar este paquete registra todas las tablas en ``Base.metadata``."""

from app.models.base import Base
from app.models.document import Document
from app.models.enums import (
    CodeSource,
    ExtractionStatus,
    FileFormat,
    RunMode,
    RunStatus,
    Severity,
)
from app.models.ingestion import IngestionRun, QualityIssue
from app.models.meta import Meta
from app.models.reference import DocumentReference, ReferenceOccurrence

__all__ = [
    "Base",
    "CodeSource",
    "Document",
    "DocumentReference",
    "ExtractionStatus",
    "FileFormat",
    "IngestionRun",
    "Meta",
    "QualityIssue",
    "ReferenceOccurrence",
    "RunMode",
    "RunStatus",
    "Severity",
]
