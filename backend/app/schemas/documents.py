from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class NormaOut(BaseModel):
    name: str
    documents: int
    references: int  # referencias que salen de documentos de la norma
    unresolved: int
    cross_norma: int  # referencias resueltas hacia otra norma


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    norma: str
    code: str
    title: str | None
    document_type: str
    system_code: str
    version: str | None
    file_format: str
    extraction_status: str
    is_active: bool
    outgoing_count: int
    incoming_count: int


class IssueOut(BaseModel):
    id: int | None  # None para las incidencias derivadas (calculadas, no almacenadas)
    source: str  # "stored" o "derived"
    norma: str | None
    type: str
    severity: str
    code: str | None
    file_path: str | None
    message: str
    details: dict[str, Any]
    created_at: datetime | None
    resolved_at: datetime | None


class DocumentDetail(DocumentSummary):
    file_path: str
    folder: str
    code_source: str | None
    references_stale: bool
    unresolved_count: int
    metadata: dict[str, Any]
    last_run_id: int | None
    last_processed_at: datetime | None
    updated_at: datetime
    open_issues: list[IssueOut]


class OccurrenceOut(BaseModel):
    group: str
    page_number: int | None
    paragraph_index: int | None
    table_index: int | None
    row_index: int | None
    cell_index: int | None
    raw_text: str
    evidence_excerpt: str | None


class ReferenceItem(BaseModel):
    code: str  # el otro extremo de la relación (citado en salientes, citante en entrantes)
    norma: str | None  # norma de ese documento; None si el citado no tiene documento
    title: str | None
    title_hint: str | None  # título con el que se cita
    document_type: str
    resolved: bool
    cross_norma: bool  # el otro extremo está en otra norma
    candidate_normas: list[str]  # citado ambiguo: normas donde existe el código
    group: str
    has_mixed_groups: bool
    occurrence_count: int
    occurrences: list[OccurrenceOut]


class ReferencesResponse(BaseModel):
    norma: str | None  # None si el código solo aparece citado, sin documento
    code: str
    resolved: bool
    outgoing: list[ReferenceItem]  # documentos que cita (resueltos)
    unresolved: list[ReferenceItem]  # códigos que cita sin documento (o ambiguos)
    incoming: list[ReferenceItem]  # documentos que lo citan
