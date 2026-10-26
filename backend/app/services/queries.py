"""Consultas de solo lectura compartidas por la CLI (y luego por la API)."""

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.meta import bump_graph_version, get_graph_version
from app.models import Document, DocumentReference, IngestionRun, QualityIssue
from app.services.graph import list_normas
from app.services.resolution import reresolve_code


def list_issues(
    session: Session,
    *,
    issue_type: str | None = None,
    severity: str | None = None,
    open_only: bool = True,
    limit: int = 200,
) -> list[QualityIssue]:
    query = select(QualityIssue).order_by(QualityIssue.id.desc()).limit(limit)
    if issue_type:
        query = query.where(QualityIssue.issue_type == issue_type)
    if severity:
        query = query.where(QualityIssue.severity == severity)
    if open_only:
        query = query.where(QualityIssue.resolved_at.is_(None))
    return list(session.scalars(query))


def list_runs(session: Session, limit: int = 20) -> list[IngestionRun]:
    return list(session.scalars(select(IngestionRun).order_by(IngestionRun.id.desc()).limit(limit)))


def stats(session: Session) -> dict[str, Any]:
    by_status = dict(
        session.execute(
            select(Document.extraction_status, func.count())
            .where(Document.is_active.is_(True))
            .group_by(Document.extraction_status)
        ).all()
    )
    by_type = dict(
        session.execute(
            select(Document.document_type, func.count())
            .where(Document.is_active.is_(True))
            .group_by(Document.document_type)
        ).all()
    )
    total_references = session.scalar(select(func.count()).select_from(DocumentReference)) or 0
    unresolved = (
        session.scalar(
            select(func.count())
            .select_from(DocumentReference)
            .where(DocumentReference.target_document_id.is_(None))
        )
        or 0
    )
    last_run = session.scalar(select(IngestionRun).order_by(IngestionRun.id.desc()).limit(1))
    return {
        "normas": [
            {
                "name": n.name,
                "documents": n.documents,
                "references": n.references,
                "unresolved": n.unresolved,
                "cross_norma": n.cross_norma,
            }
            for n in list_normas(session)
        ],
        "documents": sum(by_status.values()),
        "inactive_documents": session.scalar(
            select(func.count()).select_from(Document).where(Document.is_active.is_(False))
        )
        or 0,
        "by_status": {str(k): v for k, v in by_status.items()},
        "by_type": by_type,
        "references": total_references,
        "unresolved_references": unresolved,
        "open_issues": session.scalar(
            select(func.count()).select_from(QualityIssue).where(QualityIssue.resolved_at.is_(None))
        )
        or 0,
        "graph_version": get_graph_version(session),
        "last_run": (
            {
                "id": last_run.id,
                "status": str(last_run.status),
                "started_at": last_run.started_at.isoformat(),
            }
            if last_run
            else None
        ),
    }


def prune_missing(session: Session) -> list[str]:
    """Borra definitivamente los documentos inactivos (archivo desaparecido)."""
    rows = session.execute(
        select(Document.norma, Document.code).where(Document.is_active.is_(False))
    ).all()
    if rows:
        session.execute(delete(Document).where(Document.is_active.is_(False)))
        for code in sorted({code for _, code in rows}):
            reresolve_code(session, code)
        bump_graph_version(session)
    return [f"{norma}/{code}" for norma, code in rows]


def normas_with_document(session: Session, code: str) -> list[str]:
    """Normas donde ``code`` es un documento activo."""
    names = session.scalars(
        select(Document.norma).where(Document.code == code, Document.is_active.is_(True))
    )
    return sorted(name for name in names if name)


def is_cited(session: Session, code: str) -> bool:
    """``code`` aparece citado por algún documento activo."""
    return (
        session.scalar(
            select(DocumentReference.id)
            .join(Document, DocumentReference.source_document_id == Document.id)
            .where(DocumentReference.target_code == code, Document.is_active.is_(True))
            .limit(1)
        )
        is not None
    )
