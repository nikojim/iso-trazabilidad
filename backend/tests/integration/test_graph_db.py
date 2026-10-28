"""Grafo único construido desde SQLite y validaciones derivadas."""

from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.meta import bump_graph_version
from app.db.session import make_session_factory
from app.models import Document, DocumentReference
from app.services.graph import (
    GraphCache,
    GraphFilters,
    build_graph,
    list_normas,
    norma_names,
)
from app.services.validation import derived_issues, validate

MakeDocument = Callable[..., Document]


@pytest.fixture
def db(migrated_engine: Engine) -> Callable[[], Session]:
    return make_session_factory(migrated_engine)


def cite(
    source: Document,
    target_code: str,
    target: Document | None = None,
    *,
    group: str = "general",
    hint: str | None = None,
) -> None:
    source.outgoing_references.append(
        DocumentReference(
            target_code=target_code,
            target_document=target,
            group_name=group,
            occurrence_count=1,
            target_title_hint=hint,
        )
    )


@pytest.fixture
def populated(db: Callable[[], Session], make_document: MakeDocument) -> None:
    """Norma A: MC cita a PO (resuelto) y a ES-SGC-001 (pendiente); PR cita a MC.
    Norma B: otro MC-SGG-435 (documento distinto) que cita al PO de la norma A."""
    with db() as session, session.begin():
        manual = make_document("MC-SGG-435", title="Manual")
        policy = make_document("PO-SGS-400", title="Política de Seguridad")
        procedure = make_document("PR-SGG-101", title="Gestión del Personal")
        cite(manual, "PO-SGS-400", policy, hint="Política de Seguridad")
        cite(manual, "ES-SGC-001", hint="Política de la Calidad")
        cite(procedure, "MC-SGG-435", manual, group="procedimientos")
        other = make_document("MC-SGG-435", norma="B", file_path="B/MC.pdf")
        cite(other, "PO-SGS-400", policy)
        session.add_all([manual, policy, procedure, other])


def test_normas_are_listed_with_totals(db: Callable[[], Session], populated: None) -> None:
    with db() as session:
        summaries = {
            n.name: (n.documents, n.references, n.unresolved, n.cross_norma)
            for n in list_normas(session)
        }

    assert summaries == {"A": (3, 3, 1, 0), "B": (1, 1, 0, 1)}


def test_single_graph_with_norma_keys_and_virtual_nodes(
    db: Callable[[], Session], populated: None
) -> None:
    with db() as session:
        graph = build_graph(session)

    assert set(graph.edges) == {
        ("A/MC-SGG-435", "A/PO-SGS-400"),
        ("A/MC-SGG-435", "ES-SGC-001"),
        ("A/PR-SGG-101", "A/MC-SGG-435"),
        ("B/MC-SGG-435", "A/PO-SGS-400"),
    }
    assert graph.nodes["ES-SGC-001"]["resolved"] is False
    assert graph.nodes["ES-SGC-001"]["norma"] is None
    assert graph.nodes["ES-SGC-001"]["title"] == "Política de la Calidad"
    assert graph.nodes["B/MC-SGG-435"]["norma"] == "B"
    assert graph.nodes["B/MC-SGG-435"]["code"] == "MC-SGG-435"
    assert graph.edges["A/PR-SGG-101", "A/MC-SGG-435"]["group"] == "procedimientos"
    assert graph.edges["B/MC-SGG-435", "A/PO-SGS-400"]["cross_norma"] is True
    assert graph.edges["A/MC-SGG-435", "A/PO-SGS-400"]["cross_norma"] is False


def test_filters(db: Callable[[], Session], populated: None) -> None:
    with db() as session:
        only_general = build_graph(session, GraphFilters(groups=frozenset({"general"})))
        resolved_only = build_graph(session, GraphFilters(include_unresolved=False))

    assert ("A/PR-SGG-101", "A/MC-SGG-435") not in only_general.edges
    assert "ES-SGC-001" not in resolved_only


def test_cache_rebuilds_when_graph_version_changes(
    db: Callable[[], Session], populated: None
) -> None:
    cache = GraphCache()
    with db() as session:
        first = cache.get(session)
        assert cache.get(session) is first
        bump_graph_version(session)
        session.commit()
        assert cache.get(session) is not first


def test_loose_root_documents_are_not_a_norma(
    db: Callable[[], Session], make_document: MakeDocument
) -> None:
    with db() as session, session.begin():
        session.add(make_document("PO-SGS-400", norma="", file_path="suelto.pdf"))

    with db() as session:
        assert norma_names(session) == []
        assert build_graph(session).number_of_nodes() == 0


# ----------------------------------------------------------------------------- derivadas


def issue_types(db: Callable[[], Session]) -> dict[str, list[str | None]]:
    with db() as session:
        found: dict[str, list[str | None]] = {}
        for issue in derived_issues(session):
            found.setdefault(issue.type, []).append(issue.code)
        return found


def test_cited_title_mismatch_and_inconsistent_titles(
    db: Callable[[], Session], make_document: MakeDocument
) -> None:
    with db() as session, session.begin():
        profiles = make_document("ES-SGC-100", title="Perfiles de Cargo Dirección de Tilsor")
        manual = make_document("MC-SGG-435")
        plan = make_document("PC-SGSA-914")
        cite(manual, "ES-SGC-100", profiles, hint="Perfiles de Cargo Dirección de Tilsor")
        cite(plan, "ES-SGC-100", profiles, hint="Perfiles de Cargo Alta Gerencia")
        procedure = make_document("PR-SGG-101", title="Procedimiento de Gestión del Personal")
        cite(manual, "PR-SGG-101", procedure, hint="(Procedimiento de) Gestión del Personal")
        session.add_all([profiles, manual, plan, procedure])

    found = issue_types(db)

    assert found["cited_title_mismatch"] == ["PC-SGSA-914"]  # "(Procedimiento de)" no cuenta
    assert found["inconsistent_cited_titles"] == ["ES-SGC-100"]


def test_reference_to_inactive_and_similar_code(
    db: Callable[[], Session], make_document: MakeDocument
) -> None:
    with db() as session, session.begin():
        plan = make_document("PC-SGSA-914")
        listing = make_document("LC-SGSA-928")
        gone = make_document("PO-SGS-400", is_active=False)
        cite(plan, "RG-SGSA-928")
        cite(plan, "PO-SGS-400")
        cite(plan, "LC-SGSA-928", listing)
        session.add_all([plan, listing, gone])

    found = issue_types(db)

    assert found["unresolved_similar_code"] == ["RG-SGSA-928"]
    assert found["reference_to_inactive"] == ["PC-SGSA-914"]


def test_cycles_and_isolated_are_reported(
    db: Callable[[], Session], make_document: MakeDocument
) -> None:
    with db() as session, session.begin():
        manual = make_document("MC-SGG-435")
        plan = make_document("PC-SGSA-914")
        lonely = make_document("AX-SGC-001")
        cite(manual, "PC-SGSA-914", plan)
        cite(plan, "MC-SGG-435", manual)
        session.add_all([manual, plan, lonely])

    with db() as session:
        issues = derived_issues(session)
    cycle = next(i for i in issues if i.type == "cycle")
    isolated = next(i for i in issues if i.type == "isolated_document")

    assert (cycle.code, cycle.norma) == ("MC-SGG-435", "A")
    assert cycle.details["cycle"] == ["A/MC-SGG-435", "A/PC-SGSA-914"]
    assert (isolated.code, isolated.norma) == ("AX-SGC-001", "A")


def test_ambiguous_reference_between_normas(
    db: Callable[[], Session], make_document: MakeDocument
) -> None:
    with db() as session, session.begin():
        in_a = make_document("PR-SGI-001", norma="A", file_path="A/PR.pdf")
        in_b = make_document("PR-SGI-001", norma="B", file_path="B/PR.pdf")
        source = make_document("MC-SGG-435", norma="C", file_path="C/MC.pdf")
        cite(source, "PR-SGI-001")  # pendiente: existe en A y en B, no en C
        session.add_all([in_a, in_b, source])

    with db() as session:
        ambiguous = [i for i in derived_issues(session) if i.type == "ambiguous_reference"]

    assert [(i.code, i.norma, i.details["normas"]) for i in ambiguous] == [
        ("MC-SGG-435", "C", ["A", "B"])
    ]


def test_identical_copies_in_several_normas_are_reported(
    db: Callable[[], Session], make_document: MakeDocument
) -> None:
    with db() as session, session.begin():
        same = "a" * 64
        session.add_all(
            [
                make_document("MC-SGI-001", norma="A", file_path="A/MC.pdf", sha256=same),
                make_document("MC-SGI-001", norma="B", file_path="B/MC.pdf", sha256=same),
                make_document("PO-SGI-002", norma="A", file_path="A/PO.pdf"),
                make_document("PO-SGI-002", norma="B", file_path="B/PO.pdf"),  # contenido distinto
            ]
        )

    with db() as session:
        copies = [i for i in derived_issues(session) if i.type == "duplicate_across_normas"]

    assert [(i.code, i.norma, i.severity) for i in copies] == [
        ("MC-SGI-001", "A", "info"),
        ("MC-SGI-001", "B", "info"),
    ]
    assert copies[0].details["copies"] == ["A/MC-SGI-001", "B/MC-SGI-001"]
    assert "B/MC-SGI-001" in copies[0].message


def test_validate_reports_the_whole_graph(
    db: Callable[[], Session], populated: None, tmp_path: Path
) -> None:
    with db() as session:
        report = validate(session, tmp_path, check_hashes=False)

    assert report.unresolved == {"ES-SGC-001": ["A/MC-SGG-435"]}
    assert "A/MC-SGG-435" in report.missing_files  # los archivos del fixture no existen
    assert "B/MC-SGG-435" in report.missing_files
