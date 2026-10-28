"""Validación del estado de la base: incidencias almacenadas y derivadas sobre el grafo único.

Las derivadas no se guardan: se calculan sobre el estado actual (docs/IMPLEMENTATION_PLAN.md §4.3).
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.ingestion.normalize import normalize_text, strip_accents
from app.models import Document, DocumentReference, QualityIssue, Severity
from app.services.graph import build_graph, find_cycles, isolated_documents
from app.services.resolution import active_candidates
from app.services.scanner import sha256_of
from app.services.sync import RETRYABLE

TITLE_SIMILARITY_THRESHOLD = 0.8
_PARENTHESES = re.compile(r"\([^)]*\)")


@dataclass(frozen=True, slots=True)
class DerivedIssue:
    type: str
    severity: Severity
    code: str | None
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    norma: str | None = None  # norma del documento afectado (el que cita, si es una referencia)


@dataclass(slots=True)
class ValidationReport:
    open_issues: dict[str, dict[str, int]] = field(default_factory=dict)  # tipo -> severidad -> n
    unresolved: dict[str, list[str]] = field(default_factory=dict)  # código -> "norma/código"
    derived: list[DerivedIssue] = field(default_factory=list)
    attention: list[dict[str, str]] = field(default_factory=list)
    stale_references: list[str] = field(default_factory=list)  # "norma/código"
    missing_files: list[str] = field(default_factory=list)
    hash_drift: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        stored_errors = any(Severity.ERROR in counts for counts in self.open_issues.values())
        return stored_errors or bool(self.missing_files or self.hash_drift)


def validate(session: Session, root: Path, *, check_hashes: bool = True) -> ValidationReport:
    report = ValidationReport(
        open_issues=_open_issue_counts(session),
        unresolved=unresolved_references(session),
        derived=derived_issues(session),
    )
    for document in session.scalars(select(Document).order_by(Document.norma, Document.code)):
        if not document.is_active:
            continue
        label = f"{document.norma}/{document.code}"
        if document.extraction_status in RETRYABLE:
            report.attention.append(
                {
                    "norma": document.norma,
                    "code": document.code,
                    "status": document.extraction_status.value,
                    "file_path": document.file_path,
                }
            )
        if document.references_stale:
            report.stale_references.append(label)
        path = root / document.file_path
        if not path.exists():
            report.missing_files.append(label)
        elif check_hashes and sha256_of(path) != document.sha256:
            report.hash_drift.append(label)
    return report


def _open_issue_counts(session: Session) -> dict[str, dict[str, int]]:
    rows = session.execute(
        select(QualityIssue.issue_type, QualityIssue.severity, func.count())
        .where(QualityIssue.resolved_at.is_(None))
        .group_by(QualityIssue.issue_type, QualityIssue.severity)
    )
    counts: dict[str, dict[str, int]] = defaultdict(dict)
    for issue_type, severity, count in rows:
        counts[issue_type][severity] = count
    return dict(counts)


def unresolved_references(session: Session) -> dict[str, list[str]]:
    """Códigos citados sin destino (sin documento activo, o ambiguos entre normas)."""
    source = aliased(Document)
    rows = session.execute(
        select(DocumentReference.target_code, source.norma, source.code)
        .join(source, DocumentReference.source_document_id == source.id)
        .where(DocumentReference.target_document_id.is_(None), source.is_active.is_(True))
        .order_by(DocumentReference.target_code, source.norma, source.code)
    )
    unresolved: dict[str, list[str]] = defaultdict(list)
    for target_code, source_norma, source_code in rows:
        unresolved[target_code].append(f"{source_norma}/{source_code}")
    return dict(unresolved)


# ----------------------------------------------------------------------------- derivadas


def derived_issues(session: Session) -> list[DerivedIssue]:
    graph = build_graph(session)
    issues = []
    for cycle in find_cycles(graph):
        first = graph.nodes[cycle[0]]
        issues.append(
            DerivedIssue(
                "cycle",
                Severity.INFO,
                first["code"],
                "Referencias circulares: " + " → ".join([*cycle, cycle[0]]),
                {"cycle": cycle},
                first["norma"],
            )
        )
    for node in isolated_documents(graph):
        data = graph.nodes[node]
        issues.append(
            DerivedIssue(
                "isolated_document",
                Severity.INFO,
                data["code"],
                f"{node} no cita ni es citado",
                norma=data["norma"],
            )
        )
    issues += _copies_across_normas(session)
    references = _references_with_documents(session)
    issues += _ambiguous_references(session, references)
    issues += _references_to_inactive(session, references)
    issues += _cited_title_mismatches(references)
    issues += _inconsistent_cited_titles(references)
    issues += _similar_codes(session, references)
    return issues


@dataclass(frozen=True, slots=True)
class _Ref:
    source_norma: str
    source: str
    target_code: str
    hint: str | None
    target_title: str | None
    resolved: bool


def _references_with_documents(session: Session) -> list[_Ref]:
    source, target = aliased(Document), aliased(Document)
    rows = session.execute(
        select(
            source.norma,
            source.code,
            DocumentReference.target_code,
            DocumentReference.target_title_hint,
            target.title,
            target.id.is_not(None),
        )
        .join(source, DocumentReference.source_document_id == source.id)
        .outerjoin(target, DocumentReference.target_document_id == target.id)
        .where(source.is_active.is_(True))
        .order_by(DocumentReference.target_code, source.norma, source.code)
    )
    return [_Ref(*row) for row in rows]


def _ambiguous_references(session: Session, references: list[_Ref]) -> list[DerivedIssue]:
    """Pendientes cuyo código existe en varias normas, ninguna la del documento que cita."""
    pending = [ref for ref in references if not ref.resolved]
    candidates = active_candidates(session, {ref.target_code for ref in pending})
    issues = []
    for ref in pending:
        normas = sorted(norma for _, norma in candidates.get(ref.target_code, []))
        if len(normas) > 1:
            issues.append(
                DerivedIssue(
                    "ambiguous_reference",
                    Severity.WARNING,
                    ref.source,
                    f"{ref.source_norma}/{ref.source} cita {ref.target_code}, que existe en "
                    f"varias normas ({', '.join(normas)}); no se puede saber a cuál se refiere",
                    {"source": ref.source, "target": ref.target_code, "normas": normas},
                    ref.source_norma,
                )
            )
    return issues


def _copies_across_normas(session: Session) -> list[DerivedIssue]:
    """Un mismo archivo (mismo SHA-256) publicado en varias normas: una incidencia por copia."""
    rows = session.execute(
        select(Document.sha256, Document.norma, Document.code)
        .where(Document.is_active.is_(True))
        .order_by(Document.sha256, Document.norma, Document.code)
    )
    by_hash: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for sha256, norma, code in rows:
        by_hash[sha256].append((norma, code))
    issues = []
    for sha256, copies in by_hash.items():
        if len({norma for norma, _ in copies}) < 2:
            continue
        labels = [f"{norma}/{code}" for norma, code in copies]
        for (norma, code), label in zip(copies, labels, strict=True):
            others = ", ".join(other for other in labels if other != label)
            issues.append(
                DerivedIssue(
                    "duplicate_across_normas",
                    Severity.INFO,
                    code,
                    f"{label} es el mismo archivo que {others}: al modificarlo, actualizar todas "
                    "las copias (o dejar una sola y citarla desde las demás normas)",
                    {"copies": labels, "sha256": sha256},
                    norma,
                )
            )
    return issues


def _comparable_titles(title: str) -> set[str]:
    """Variantes sin tildes ni mayúsculas: sin el texto entre paréntesis y sin los paréntesis.

    "(Procedimiento de) Compras" se compara como "compras" y como "procedimiento de compras".
    """

    def clean(text: str) -> str:
        return strip_accents(normalize_text(text)).casefold().strip()

    return {clean(_PARENTHESES.sub(" ", title)), clean(title.replace("(", " ").replace(")", " "))}


def _similar(a: str, b: str) -> bool:
    for left in _comparable_titles(a):
        for right in _comparable_titles(b):
            if left and right and (left in right or right in left):
                return True
            if SequenceMatcher(None, left, right).ratio() >= TITLE_SIMILARITY_THRESHOLD:
                return True
    return False


def _cited_title_mismatches(references: list[_Ref]) -> list[DerivedIssue]:
    return [
        DerivedIssue(
            "cited_title_mismatch",
            Severity.WARNING,
            ref.source,
            f"{ref.source} cita {ref.target_code} como {ref.hint!r}, pero su título es "
            f"{ref.target_title!r}",
            {
                "source": ref.source,
                "target": ref.target_code,
                "cited": ref.hint,
                "actual": ref.target_title,
            },
            ref.source_norma,
        )
        for ref in references
        if ref.hint and ref.target_title and not _similar(ref.hint, ref.target_title)
    ]


def _inconsistent_cited_titles(references: list[_Ref]) -> list[DerivedIssue]:
    hints: dict[str, dict[str, str]] = defaultdict(dict)  # destino -> origen -> título citado
    for ref in references:
        if ref.hint:
            hints[ref.target_code][f"{ref.source_norma}/{ref.source}"] = ref.hint
    issues = []
    for target, by_source in hints.items():
        conflicting = {
            (a, b)
            for a, b in combinations(sorted(by_source), 2)
            if not _similar(by_source[a], by_source[b])
        }
        if conflicting:
            issues.append(
                DerivedIssue(
                    "inconsistent_cited_titles",
                    Severity.WARNING,
                    target,
                    f"{target} se cita con títulos distintos según el documento",
                    {"titles": by_source},
                )
            )
    return issues


def _references_to_inactive(session: Session, references: list[_Ref]) -> list[DerivedIssue]:
    rows = session.execute(select(Document.code, Document.is_active)).all()
    active = {code for code, is_active in rows if is_active}
    inactive = {code for code, is_active in rows if not is_active} - active
    return [
        DerivedIssue(
            "reference_to_inactive",
            Severity.WARNING,
            ref.source,
            f"{ref.source} cita {ref.target_code}, cuyo archivo ya no existe",
            {"source": ref.source, "target": ref.target_code},
            ref.source_norma,
        )
        for ref in references
        if not ref.resolved and ref.target_code in inactive
    ]


def _similar_codes(session: Session, references: list[_Ref]) -> list[DerivedIssue]:
    """Pendientes con el mismo sistema y número que un documento existente de otro prefijo."""
    existing: dict[tuple[str, str], list[str]] = defaultdict(list)
    active_codes = set(session.scalars(select(Document.code).where(Document.is_active.is_(True))))
    for code in sorted(active_codes):
        _, system, number = code.split("-")
        existing[(system, number)].append(code)
    issues = []
    for target in sorted({ref.target_code for ref in references if not ref.resolved}):
        _, system, number = target.split("-")
        candidates = [code for code in existing.get((system, number), []) if code != target]
        if candidates:
            issues.append(
                DerivedIssue(
                    "unresolved_similar_code",
                    Severity.WARNING,
                    target,
                    f"{target} no existe; ¿quiso decir {', '.join(candidates)}?",
                    {"target": target, "candidates": candidates},
                )
            )
    return issues
