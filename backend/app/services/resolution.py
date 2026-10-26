"""Resolución de códigos citados en el grafo único (CLAUDE.md, regla 11).

``A`` (norma N) cita el código C:
1. Si C existe activo en la norma N, la referencia apunta a ese documento.
2. Si no, y C existe activo en **exactamente una** otra norma, apunta a ese (referencia cruzada).
3. Si C existe en varias otras normas, la referencia queda pendiente (``target_document_id``
   NULL) y la validación la informa como ``ambiguous_reference``.

La resolución se recalcula por código (``reresolve_code``) cada vez que un documento con ese
código aparece, se reactiva, se da de baja o se reemplaza: una segunda copia en otra norma
puede volver ambigua una referencia que antes estaba resuelta.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, DocumentReference

Candidate = tuple[int, str]  # (id del documento, norma)


@dataclass(frozen=True, slots=True)
class Resolution:
    target_id: int | None
    cross_norma: bool = False
    ambiguous_normas: tuple[str, ...] = ()  # normas candidatas cuando no se puede elegir


@dataclass(frozen=True, slots=True)
class ResolutionChange:
    """Una referencia cuyo destino cambió al recalcular la resolución de su código."""

    source: str  # "norma/código" del documento que cita
    target_code: str
    before: str | None  # "norma/código" del destino anterior; None si estaba pendiente
    after: str | None  # "norma/código" del destino nuevo; None si queda pendiente
    ambiguous_normas: tuple[str, ...] = ()


def choose_target(source_norma: str, candidates: Sequence[Candidate]) -> Resolution:
    same_norma = [doc_id for doc_id, norma in candidates if norma == source_norma]
    if same_norma:
        return Resolution(same_norma[0])
    if len(candidates) == 1:
        return Resolution(candidates[0][0], cross_norma=True)
    return Resolution(None, ambiguous_normas=tuple(sorted(norma for _, norma in candidates)))


def active_candidates(session: Session, codes: Iterable[str]) -> dict[str, list[Candidate]]:
    """Documentos activos con cada código, en todas las normas."""
    codes = list(codes)
    if not codes:
        return {}
    rows = session.execute(
        select(Document.code, Document.id, Document.norma)
        .where(Document.code.in_(codes), Document.is_active.is_(True))
        .order_by(Document.norma)
    )
    found: dict[str, list[Candidate]] = defaultdict(list)
    for code, doc_id, norma in rows:
        found[code].append((doc_id, norma))
    return dict(found)


def reresolve_code(session: Session, code: str) -> list[ResolutionChange]:
    """Recalcula el destino de todas las referencias a ``code``; devuelve las que cambiaron."""
    session.flush()
    candidates = active_candidates(session, [code]).get(code, [])
    normas = dict(
        session.execute(select(Document.id, Document.norma).where(Document.code == code)).all()
    )

    def label(doc_id: int | None) -> str | None:
        return None if doc_id is None else f"{normas.get(doc_id, '(eliminado)')}/{code}"

    rows = session.execute(
        select(DocumentReference, Document.norma, Document.code)
        .join(Document, DocumentReference.source_document_id == Document.id)
        .where(DocumentReference.target_code == code)
        .order_by(Document.norma, Document.code)
        # La base pudo poner NULL por ON DELETE SET NULL: leer el valor actual, no el cacheado.
        .execution_options(populate_existing=True)
    ).all()
    changes = []
    for reference, source_norma, source_code in rows:
        resolution = choose_target(source_norma, candidates)
        if reference.target_document_id == resolution.target_id:
            continue
        changes.append(
            ResolutionChange(
                source=f"{source_norma}/{source_code}",
                target_code=code,
                before=label(reference.target_document_id),
                after=label(resolution.target_id),
                ambiguous_normas=resolution.ambiguous_normas,
            )
        )
        reference.target_document_id = resolution.target_id
    session.flush()
    return changes
