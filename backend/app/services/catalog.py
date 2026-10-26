"""Consultas de solo lectura para la API: búsqueda, detalle, referencias e incidencias."""

from typing import Literal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, aliased, selectinload

from app.ingestion.codes import split_code
from app.models import Document, DocumentReference, IngestionRun, QualityIssue
from app.schemas.documents import (
    DocumentDetail,
    DocumentSummary,
    IssueOut,
    OccurrenceOut,
    ReferenceItem,
    ReferencesResponse,
)
from app.schemas.graph import RunOut, UnresolvedOut
from app.services import queries
from app.services.graph import node_key, norma_names
from app.services.resolution import active_candidates
from app.services.validation import derived_issues, unresolved_references

SortField = Literal["norma", "code", "title", "updated_at"]


class NormaRequiredError(LookupError):
    """El código es un documento en varias normas: hay que indicar cuál."""

    def __init__(self, code: str, normas: list[str]) -> None:
        super().__init__(f"{code} es un documento en varias normas; indicar ?norma=")
        self.code = code
        self.normas = normas


class CodeNotFoundError(LookupError):
    """El código no es un documento (en la norma indicada) ni un código citado."""


class UnknownNormaError(LookupError):
    """No existe una norma con ese nombre."""


def normalize_code(code: str) -> str:
    return code.strip().upper()


def check_norma(session: Session, norma: str | None) -> None:
    if norma is not None and norma not in norma_names(session):
        raise UnknownNormaError(f"No existe la norma {norma!r}")


def resolve_norma(session: Session, code: str, norma: str | None) -> str | None:
    """Norma del documento ``code``; ``None`` si el código solo aparece citado (sin documento).

    Sin ``norma``, el código debe ser documento en una sola norma (si no, 409).
    """
    check_norma(session, norma)
    found = queries.normas_with_document(session, code)
    if norma is not None:
        if norma not in found:
            raise CodeNotFoundError(f"{code} no es un documento de la norma {norma!r}")
        return norma
    if len(found) > 1:
        raise NormaRequiredError(code, found)
    if found:
        return found[0]
    if queries.is_cited(session, code):
        return None
    raise CodeNotFoundError(f"{code} no es un documento ni un código citado")


def resolve_node(session: Session, code: str, norma: str | None) -> str:
    """Clave del nodo en el grafo: ``norma/código`` o, si solo está citado, el código."""
    resolved = resolve_norma(session, code, norma)
    return node_key(resolved, code) if resolved is not None else code


# ----------------------------------------------------------------------------- documentos


def _with_counts() -> Select[tuple[Document, int, int]]:
    outgoing = (
        select(func.count())
        .where(DocumentReference.source_document_id == Document.id)
        .correlate(Document)
        .scalar_subquery()
    )
    incoming = (
        select(func.count())
        .where(DocumentReference.target_document_id == Document.id)
        .correlate(Document)
        .scalar_subquery()
    )
    return select(Document, outgoing.label("outgoing"), incoming.label("incoming"))


def _summary(document: Document, outgoing: int, incoming: int) -> DocumentSummary:
    return DocumentSummary(
        norma=document.norma,
        code=document.code,
        title=document.title,
        document_type=document.document_type,
        system_code=document.system_code,
        version=document.version,
        file_format=document.file_format.value,
        extraction_status=document.extraction_status.value,
        is_active=document.is_active,
        outgoing_count=outgoing,
        incoming_count=incoming,
    )


def search_documents(
    session: Session,
    *,
    query: str | None,
    norma: str | None,
    document_type: str | None,
    system: str | None,
    folder: str | None,
    status: str | None,
    active: bool | None,
    sort: SortField,
    page: int,
    page_size: int,
) -> tuple[list[DocumentSummary], int]:
    check_norma(session, norma)
    conditions = [Document.norma != ""]
    if query:
        pattern = f"%{query.strip()}%"
        conditions.append(or_(Document.code.ilike(pattern), Document.title.ilike(pattern)))
    if norma:
        conditions.append(Document.norma == norma)
    if document_type:
        conditions.append(Document.document_type == document_type.upper())
    if system:
        conditions.append(Document.system_code == system.upper())
    if folder:
        conditions.append(Document.folder.ilike(f"{folder}%"))
    if status:
        conditions.append(Document.extraction_status == status)
    if active is not None:
        conditions.append(Document.is_active.is_(active))

    total = session.scalar(select(func.count()).select_from(Document).where(*conditions)) or 0
    # Organizados por norma y nombre; sin título, el código ordena dentro de la norma.
    order = {
        "norma": (Document.norma, func.coalesce(Document.title, Document.code), Document.code),
        "code": (Document.code, Document.norma),
        "title": (Document.title, Document.code),
        "updated_at": (Document.updated_at.desc(), Document.code),
    }[sort]
    rows = session.execute(
        _with_counts()
        .where(*conditions)
        .order_by(*order)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [_summary(*row) for row in rows], total


def get_document(session: Session, norma: str | None, code: str) -> DocumentDetail:
    row = (
        session.execute(
            _with_counts().where(Document.norma == norma, Document.code == code)
        ).first()
        if norma is not None
        else None
    )
    if row is None:
        raise CodeNotFoundError(f"{code} no es un documento (solo está citado)")
    document, outgoing, incoming = row
    unresolved = (
        session.scalar(
            select(func.count()).where(
                DocumentReference.source_document_id == document.id,
                DocumentReference.target_document_id.is_(None),
            )
        )
        or 0
    )
    issues = session.scalars(
        select(QualityIssue)
        .where(QualityIssue.document_id == document.id, QualityIssue.resolved_at.is_(None))
        .order_by(QualityIssue.id)
    )
    summary = _summary(document, outgoing, incoming)
    return DocumentDetail(
        **summary.model_dump(),
        file_path=document.file_path,
        folder=document.folder,
        code_source=document.code_source.value if document.code_source else None,
        references_stale=document.references_stale,
        unresolved_count=unresolved,
        metadata=document.metadata_json,
        last_run_id=document.last_run_id,
        last_processed_at=document.last_processed_at,
        updated_at=document.updated_at,
        open_issues=[stored_issue_out(issue, document.norma) for issue in issues],
    )


# ----------------------------------------------------------------------------- referencias


def _occurrences(reference: DocumentReference) -> list[OccurrenceOut]:
    return [
        OccurrenceOut(
            group=o.group_name,
            page_number=o.page_number,
            paragraph_index=o.paragraph_index,
            table_index=o.table_index,
            row_index=o.row_index,
            cell_index=o.cell_index,
            raw_text=o.raw_text,
            evidence_excerpt=o.evidence_excerpt,
        )
        for o in reference.occurrences
    ]


def _item(
    reference: DocumentReference,
    code: str,
    title: str | None,
    *,
    norma: str | None,
    cross_norma: bool = False,
    candidate_normas: list[str] | None = None,
) -> ReferenceItem:
    return ReferenceItem(
        code=code,
        norma=norma,
        title=title,
        title_hint=reference.target_title_hint,
        document_type=split_code(code)[0],
        resolved=norma is not None,
        cross_norma=cross_norma,
        candidate_normas=candidate_normas or [],
        group=reference.group_name,
        has_mixed_groups=reference.has_mixed_groups,
        occurrence_count=reference.occurrence_count,
        occurrences=_occurrences(reference),
    )


def references_of(session: Session, norma: str | None, code: str) -> ReferencesResponse:
    document = (
        session.scalar(
            select(Document)
            .where(Document.norma == norma, Document.code == code, Document.is_active.is_(True))
            .options(
                selectinload(Document.outgoing_references).selectinload(
                    DocumentReference.target_document
                ),
                selectinload(Document.outgoing_references).selectinload(
                    DocumentReference.occurrences
                ),
            )
        )
        if norma is not None
        else None
    )
    outgoing: list[ReferenceItem] = []
    unresolved: list[ReferenceItem] = []
    if document is not None:
        references = sorted(document.outgoing_references, key=lambda r: r.target_code)
        pending = [r.target_code for r in references if r.target_document is None]
        candidates = active_candidates(session, pending)
        for reference in references:
            target = reference.target_document
            if target is not None:
                outgoing.append(
                    _item(
                        reference,
                        reference.target_code,
                        target.title,
                        norma=target.norma,
                        cross_norma=target.norma != document.norma,
                    )
                )
            else:
                # Pendiente: sin documento, o con documento en varias normas (ambigua).
                normas = sorted(n for _, n in candidates.get(reference.target_code, []))
                unresolved.append(
                    _item(
                        reference,
                        reference.target_code,
                        reference.target_title_hint,
                        norma=None,
                        candidate_normas=normas,
                    )
                )

    # Entrantes: quienes citan este documento (o este código, si todavía no tiene documento).
    source = aliased(Document)
    incoming_query = (
        select(DocumentReference, source)
        .join(source, DocumentReference.source_document_id == source.id)
        .where(source.is_active.is_(True))
        .options(selectinload(DocumentReference.occurrences))
        .order_by(source.norma, source.code)
    )
    if document is not None:
        incoming_query = incoming_query.where(DocumentReference.target_document_id == document.id)
    else:
        incoming_query = incoming_query.where(
            DocumentReference.target_code == code, DocumentReference.target_document_id.is_(None)
        )
    incoming = [
        _item(
            reference,
            src.code,
            src.title,
            norma=src.norma,
            cross_norma=document is not None and src.norma != document.norma,
        )
        for reference, src in session.execute(incoming_query).all()
    ]
    return ReferencesResponse(
        norma=document.norma if document is not None else None,
        code=code,
        resolved=document is not None,
        outgoing=outgoing,
        unresolved=unresolved,
        incoming=incoming,
    )


def unresolved_list(session: Session, norma: str | None, query: str | None) -> list[UnresolvedOut]:
    """Códigos citados sin destino; con ``norma``, solo los citados desde esa norma."""
    check_norma(session, norma)
    hints = dict(
        session.execute(
            select(DocumentReference.target_code, func.max(DocumentReference.target_title_hint))
            .where(DocumentReference.target_document_id.is_(None))
            .group_by(DocumentReference.target_code)
        ).all()
    )
    pending = unresolved_references(session)
    candidates = active_candidates(session, pending)
    items = []
    for code, sources in pending.items():
        if query and query.upper() not in code:
            continue
        if norma is not None:
            sources = [s for s in sources if s.split("/", 1)[0] == norma]
            if not sources:
                continue
        items.append(
            UnresolvedOut(
                target_code=code,
                title_hint=hints.get(code),
                cited_by_count=len(sources),
                cited_by=sources,
                candidate_normas=sorted(n for _, n in candidates.get(code, [])),
            )
        )
    return items


# ----------------------------------------------------------------------------- incidencias


def _norma_of_path(file_path: str | None) -> str | None:
    if not file_path or "/" not in file_path:
        return None
    return file_path.split("/", 1)[0]


def stored_issue_out(issue: QualityIssue, norma: str | None = None) -> IssueOut:
    return IssueOut(
        id=issue.id,
        source="stored",
        norma=norma or _norma_of_path(issue.file_path),
        type=issue.issue_type,
        severity=issue.severity.value,
        code=issue.code,
        file_path=issue.file_path,
        message=issue.message,
        details=issue.details_json,
        created_at=issue.created_at,
        resolved_at=issue.resolved_at,
    )


def list_issues(
    session: Session,
    *,
    norma: str | None,
    issue_type: str | None,
    severity: str | None,
    code: str | None,
    open_only: bool,
    include_derived: bool,
) -> list[IssueOut]:
    """Incidencias almacenadas (de la ingesta) y derivadas (calculadas sobre el estado actual)."""
    check_norma(session, norma)
    stored_query = select(QualityIssue).order_by(QualityIssue.id.desc())
    if open_only:
        stored_query = stored_query.where(QualityIssue.resolved_at.is_(None))
    issues = [stored_issue_out(issue) for issue in session.scalars(stored_query)]
    if include_derived:
        issues += [
            IssueOut(
                id=None,
                source="derived",
                norma=issue.norma,
                type=issue.type,
                severity=issue.severity.value,
                code=issue.code,
                file_path=None,
                message=issue.message,
                details=issue.details,
                created_at=None,
                resolved_at=None,
            )
            for issue in derived_issues(session)
        ]
    return [
        issue
        for issue in issues
        if (norma is None or issue.norma == norma)
        and (issue_type is None or issue.type == issue_type)
        and (severity is None or issue.severity == severity)
        and (code is None or issue.code == code)
    ]


def list_runs(session: Session, page: int, page_size: int) -> tuple[list[RunOut], int]:
    total = session.scalar(select(func.count()).select_from(IngestionRun)) or 0
    runs = session.scalars(
        select(IngestionRun)
        .order_by(IngestionRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return [run_out(run) for run in runs], total


def run_out(run: IngestionRun) -> RunOut:
    return RunOut(
        id=run.id,
        mode=run.mode.value,
        status=run.status.value,
        root_path=run.root_path,
        started_at=run.started_at,
        ended_at=run.ended_at,
        processed_count=run.processed_count,
        skipped_count=run.skipped_count,
        error_count=run.error_count,
        warning_count=run.warning_count,
        new_count=run.new_count,
        updated_count=run.updated_count,
        missing_count=run.missing_count,
        no_section_count=run.no_section_count,
        unsupported_skipped_count=run.unsupported_skipped_count,
        root_files_count=run.root_files_count,
        references_count=run.references_count,
        occurrences_count=run.occurrences_count,
        duplicate_references_count=run.duplicate_references_count,
        unresolved_count=run.unresolved_count,
        log_path=run.log_path,
    )
