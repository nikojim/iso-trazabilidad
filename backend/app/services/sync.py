"""Escrituras de un documento dentro de la transacción que abre la ingesta.

Reglas (CLAUDE.md 4, 6, 7 y 8): las referencias se reemplazan solo con un resultado
publicable; una falla de lectura, OCR o sección nunca borra las vigentes; una relación
lógica por (origen, código destino) con sus ocurrencias como evidencia.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.meta import bump_graph_version
from app.ingestion.codes import split_code
from app.ingestion.types import ExtractionResult, Issue, ReferenceHit
from app.models import (
    Document,
    DocumentReference,
    ExtractionStatus,
    QualityIssue,
    ReferenceOccurrence,
    Severity,
)
from app.models.base import utcnow
from app.services.resolution import (
    ResolutionChange,
    active_candidates,
    choose_target,
    reresolve_code,
)
from app.services.scanner import ScannedFile

PUBLISHABLE = frozenset(
    {ExtractionStatus.OK, ExtractionStatus.NO_REFERENCES, ExtractionStatus.NOT_APPLICABLE}
)
RETRYABLE = frozenset(
    {
        ExtractionStatus.ERROR,
        ExtractionStatus.NEEDS_REVIEW,
        ExtractionStatus.REQUIRES_OCR,
        ExtractionStatus.SOURCE_CODE_UNRESOLVED,
    }
)


@dataclass(slots=True)
class ReferenceStats:
    """Cómo quedaron las referencias salientes de un documento al publicarlo."""

    total: int = 0
    occurrences: int = 0
    duplicates: int = 0  # relaciones que aparecen más de una vez en la sección
    added: int = 0
    removed: int = 0
    same_norma: int = 0
    cross_norma: int = 0
    unresolved: int = 0
    ambiguous: list[str] = field(default_factory=list)  # códigos presentes en varias normas
    changed: bool = False


@dataclass(frozen=True, slots=True)
class SyncOutcome:
    document_id: int
    created: bool
    references_changed: bool
    references: ReferenceStats | None = None  # None: se conservaron las referencias vigentes
    resolution_changes: tuple[ResolutionChange, ...] = ()


# ----------------------------------------------------------------------------- incidencias


def close_open_issues(session: Session, *, document_id: int | None, file_path: str) -> None:
    """Cierra las incidencias abiertas del documento (o del archivo, si no hay documento)."""
    condition = (
        QualityIssue.document_id == document_id
        if document_id is not None
        else (QualityIssue.file_path == file_path) & QualityIssue.document_id.is_(None)
    )
    session.execute(
        update(QualityIssue)
        .where(condition, QualityIssue.resolved_at.is_(None))
        .values(resolved_at=utcnow())
    )


def record_issues(
    session: Session,
    issues: Iterable[Issue],
    *,
    run_id: int | None,
    document_id: int | None,
    file_path: str | None,
    code: str | None,
) -> int:
    """Guarda incidencias; devuelve cuántas son de severidad warning."""
    warnings = 0
    for issue in issues:
        warnings += issue.severity is Severity.WARNING
        session.add(
            QualityIssue(
                run_id=run_id,
                document_id=document_id,
                file_path=file_path,
                code=code,
                issue_type=issue.type,
                severity=issue.severity,
                message=issue.message,
                details_json=issue.details,
            )
        )
    return warnings


# ----------------------------------------------------------------------------- documentos


def find_by_code(session: Session, norma: str, code: str) -> Document | None:
    """El código es único dentro de una norma (carpeta raíz), no en toda la base."""
    return session.scalar(select(Document).where(Document.norma == norma, Document.code == code))


def find_by_path(session: Session, rel_path: str) -> Document | None:
    return session.scalar(select(Document).where(Document.file_path == rel_path))


def publish(
    session: Session,
    *,
    file: ScannedFile,
    sha256: str,
    result: ExtractionResult,
    run_id: int,
    document: Document | None,
    extra_issues: Iterable[Issue] = (),
) -> SyncOutcome:
    """Crea o actualiza el documento de ``result.source_code`` y, si corresponde, sus referencias.

    ``document`` es el registro existente que este archivo actualiza (ya decidido por la
    ingesta: mismo código, o mismo código con el archivo movido); ``None`` crea uno nuevo.
    """
    assert result.source_code is not None, "publish exige un código de origen confirmado"
    created = document is None
    if document is None:
        document_type, system_code = split_code(result.source_code)
        assert file.norma is not None, "un archivo suelto en la raíz no tiene norma"
        document = Document(
            norma=file.norma,
            code=result.source_code,
            document_type=document_type,
            system_code=system_code,
        )
        session.add(document)
    was_active = document.is_active is not False
    _apply_file_fields(document, file, sha256, result, run_id)
    session.flush()

    issues = [*result.issues, *extra_issues]
    stats: ReferenceStats | None = None
    if result.status in PUBLISHABLE:
        stats = replace_references(session, document, result.references)
        document.references_sha256 = sha256
    elif result.status is ExtractionStatus.NO_SECTION:
        if document.outgoing_references:
            issues.append(
                Issue(
                    "section_lost",
                    Severity.WARNING,
                    "El documento ya no tiene sección REFERENCIAS; se conservan las referencias "
                    "vigentes",
                    {"references": len(document.outgoing_references)},
                )
            )
        else:
            document.references_sha256 = sha256

    changes: list[ResolutionChange] = []
    if created or not was_active:
        changes = reresolve_code(session, document.code)
    close_open_issues(session, document_id=document.id, file_path=file.rel_path)
    close_open_issues(session, document_id=None, file_path=file.rel_path)
    record_issues(
        session,
        issues,
        run_id=run_id,
        document_id=document.id,
        file_path=file.rel_path,
        code=document.code,
    )
    bump_graph_version(session)
    return SyncOutcome(document.id, created, bool(stats and stats.changed), stats, tuple(changes))


def mark_unpublished(
    session: Session,
    *,
    file: ScannedFile,
    sha256: str,
    result: ExtractionResult,
    run_id: int,
    extra_issues: Iterable[Issue] = (),
) -> int | None:
    """Registra un archivo que no se puede publicar (código dudoso, ilegible, bloqueado).

    Si la ruta ya pertenece a un documento, actualiza su estado y hash pero **no** toca
    sus referencias ni su código. Devuelve el id de ese documento, si existe.
    """
    document = find_by_path(session, file.rel_path)
    issues = [*result.issues, *extra_issues]
    if document is not None:
        document.sha256 = sha256
        document.extraction_status = (
            result.status if result.status in RETRYABLE else ExtractionStatus.SOURCE_CODE_UNRESOLVED
        )
        document.last_run_id = run_id
        document.last_processed_at = utcnow()
        close_open_issues(session, document_id=document.id, file_path=file.rel_path)
    close_open_issues(session, document_id=None, file_path=file.rel_path)
    record_issues(
        session,
        issues,
        run_id=run_id,
        document_id=document.id if document else None,
        file_path=file.rel_path,
        code=result.source_code or (document.code if document else None),
    )
    return document.id if document else None


def _apply_file_fields(
    document: Document, file: ScannedFile, sha256: str, result: ExtractionResult, run_id: int
) -> None:
    document.title = result.title or document.title
    document.version = result.version or document.version
    document.file_path = file.rel_path
    document.folder = file.folder
    document.file_format = file.file_format
    document.file_size = file.size
    document.file_mtime = file.mtime
    document.sha256 = sha256
    document.extraction_status = result.status
    document.code_source = result.code_source
    document.is_active = True
    document.metadata_json = {
        **result.metadata,
        "page_count": result.page_count,
        "ocr_pages": result.ocr_pages,
        "section": (
            {
                "start_page": result.section.start_page,
                "end_page": result.section.end_page,
                "terminator": result.section.terminator,
            }
            if result.section
            else None
        ),
    }
    document.last_run_id = run_id
    document.last_processed_at = utcnow()


# ----------------------------------------------------------------------------- referencias


def replace_references(
    session: Session, document: Document, hits: list[ReferenceHit]
) -> ReferenceStats:
    """Diff del conjunto de referencias del documento, con la resolución de cada destino."""
    current = {ref.target_code: ref for ref in document.outgoing_references}
    wanted = {hit.code: hit for hit in hits}
    stats = ReferenceStats(
        total=len(wanted),
        occurrences=sum(len(hit.occurrences) for hit in hits),
        duplicates=sum(1 for hit in hits if len(hit.occurrences) > 1),
    )

    for code, reference in current.items():
        if code not in wanted:
            document.outgoing_references.remove(reference)
            stats.removed += 1

    candidates = active_candidates(session, wanted)
    for code, hit in wanted.items():
        reference = current.get(code)
        if reference is None:
            reference = DocumentReference(target_code=code)
            document.outgoing_references.append(reference)
            stats.added += 1
        elif _evidence_key(reference) != _hit_key(hit):
            stats.changed = True
        resolution = choose_target(document.norma, candidates.get(code, []))
        if resolution.target_id is None:
            stats.unresolved += 1
            if resolution.ambiguous_normas:
                stats.ambiguous.append(code)
        elif resolution.cross_norma:
            stats.cross_norma += 1
        else:
            stats.same_norma += 1
        reference.target_document_id = resolution.target_id
        reference.group_name = hit.group
        reference.has_mixed_groups = hit.has_mixed_groups
        reference.occurrence_count = len(hit.occurrences)
        reference.target_title_hint = hit.title_hint
        reference.occurrences = [
            ReferenceOccurrence(
                group_name=o.group,
                ordinal=o.ordinal,
                page_number=o.page_number,
                paragraph_index=o.paragraph_index,
                table_index=o.table_index,
                row_index=o.row_index,
                cell_index=o.cell_index,
                raw_text=o.raw_text,
                evidence_excerpt=o.evidence_excerpt,
            )
            for o in hit.occurrences
        ]
    session.flush()
    stats.changed = stats.changed or bool(stats.added or stats.removed)
    return stats


def _evidence_key(reference: DocumentReference) -> tuple[object, ...]:
    return (
        reference.group_name,
        reference.has_mixed_groups,
        reference.target_title_hint,
        tuple((o.group_name, o.page_number, o.raw_text) for o in reference.occurrences),
    )


def _hit_key(hit: ReferenceHit) -> tuple[object, ...]:
    return (
        hit.group,
        hit.has_mixed_groups,
        hit.title_hint,
        tuple((o.group, o.page_number, o.raw_text) for o in hit.occurrences),
    )


def deactivate_missing(session: Session, document: Document, run_id: int) -> list[ResolutionChange]:
    """El archivo desapareció: baja lógica. Quienes lo citan se re-resuelven: pasan a otra
    norma que tenga el mismo código, si es la única, o vuelven a quedar pendientes."""
    document.is_active = False
    document.last_run_id = run_id
    changes = reresolve_code(session, document.code)
    close_open_issues(session, document_id=document.id, file_path=document.file_path)
    record_issues(
        session,
        [
            Issue(
                "file_missing",
                Severity.WARNING,
                f"El archivo {document.file_path} ya no existe; el documento queda inactivo",
            )
        ],
        run_id=run_id,
        document_id=document.id,
        file_path=document.file_path,
        code=document.code,
    )
    bump_graph_version(session)
    return changes
