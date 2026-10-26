from collections.abc import Callable

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.meta import bump_graph_version, get_graph_version
from app.models import Document, DocumentReference, ReferenceOccurrence

MakeDocument = Callable[..., Document]


def _reference(source: Document, target_code: str, **overrides: object) -> DocumentReference:
    values: dict[str, object] = {
        "source_document": source,
        "target_code": target_code,
        "group_name": "general",
        "occurrence_count": 1,
    }
    values.update(overrides)
    return DocumentReference(**values)


def test_document_code_is_unique_within_a_norma(
    session: Session, make_document: MakeDocument
) -> None:
    session.add(make_document("PO-SGS-400"))
    session.add(make_document("PO-SGS-400", file_path="A/otra/ruta.pdf"))

    with pytest.raises(IntegrityError):
        session.flush()


def test_same_code_allowed_in_another_norma(session: Session, make_document: MakeDocument) -> None:
    session.add(make_document("PO-SGS-400"))
    session.add(make_document("PO-SGS-400", norma="B", file_path="B/PO-SGS-400.pdf"))

    session.flush()


def test_reference_pair_is_unique(session: Session, make_document: MakeDocument) -> None:
    source = make_document("MC-SGG-435")
    session.add_all([_reference(source, "PR-SGG-101"), _reference(source, "PR-SGG-101")])

    with pytest.raises(IntegrityError):
        session.flush()


def test_target_code_must_be_uppercase(session: Session, make_document: MakeDocument) -> None:
    session.add(_reference(make_document("MC-SGG-435"), "pr-sgg-101"))

    with pytest.raises(IntegrityError):
        session.flush()


def test_invalid_extraction_status_rejected(session: Session, make_document: MakeDocument) -> None:
    session.add(make_document())
    session.flush()

    with pytest.raises(IntegrityError):
        session.execute(text("UPDATE documents SET extraction_status = 'inventado'"))


def test_foreign_keys_enforced(session: Session) -> None:
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO document_references "
                "(source_document_id, target_code, group_name, has_mixed_groups, "
                "occurrence_count, created_at, updated_at) "
                "VALUES (999, 'PO-SGS-400', 'general', 0, 1, '2026-01-01', '2026-01-01')"
            )
        )


def test_pending_reference_allows_null_target(
    session: Session, make_document: MakeDocument
) -> None:
    reference = _reference(make_document("MC-SGG-435"), "ES-SGC-001")
    session.add(reference)
    session.flush()

    assert reference.target_document_id is None


def test_deleting_source_cascades_to_references_and_occurrences(
    session: Session, make_document: MakeDocument
) -> None:
    source = make_document("MC-SGG-435")
    reference = _reference(source, "PR-SGG-101", occurrence_count=2)
    reference.occurrences = [
        ReferenceOccurrence(group_name="procedimientos", ordinal=i, raw_text="[PR-SGG-101]")
        for i in (1, 2)
    ]
    session.add(source)
    session.flush()

    session.execute(text("DELETE FROM documents WHERE code = 'MC-SGG-435'"))

    assert session.scalar(select(DocumentReference.id)) is None
    assert session.scalar(select(ReferenceOccurrence.id)) is None


def test_deleting_target_sets_reference_pending(
    session: Session, make_document: MakeDocument
) -> None:
    source = make_document("MC-SGG-435")
    target = make_document("ES-SGC-001")
    reference = _reference(source, "ES-SGC-001", target_document=target)
    session.add_all([source, target])
    session.flush()

    session.execute(text("DELETE FROM documents WHERE code = 'ES-SGC-001'"))
    session.expire_all()

    reference = session.scalars(select(DocumentReference)).one()
    assert reference.target_document_id is None
    assert reference.target_code == "ES-SGC-001"


def test_references_stale_flag(make_document: MakeDocument) -> None:
    document = make_document(sha256="b" * 64, references_sha256="a" * 64)
    assert document.references_stale

    document.references_sha256 = document.sha256
    assert not document.references_stale


def test_graph_version_seeded_and_bumped(session: Session) -> None:
    assert get_graph_version(session) == 0

    assert bump_graph_version(session) == 1
    assert bump_graph_version(session) == 2
    assert get_graph_version(session) == 2
