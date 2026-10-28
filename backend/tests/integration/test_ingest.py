"""Ingesta incremental y transaccional sobre documentos sintéticos (SKILL, casos 3, 4, 5 y 8)."""

import os
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db.session import make_session_factory
from app.ingestion.config import ExtractionConfig
from app.models import (
    Document,
    DocumentReference,
    ExtractionStatus,
    FileFormat,
    IngestionRun,
    QualityIssue,
    RunStatus,
)
from app.services import sync
from app.services.ingest import (
    IngestionLockedError,
    IngestionService,
    IngestOptions,
    UnsupportedFileError,
)
from app.services.queries import prune_missing
from app.services.scanner import PathOutsideRootError
from tests.fixtures.builders import (
    Heading,
    Line,
    Para,
    build_docx,
    build_pdf,
    build_xlsx,
    heading,
    ref,
)

INCREMENTAL = IngestOptions(incremental=True)


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    root = tmp_path / "documents"
    (root / "A").mkdir(parents=True)  # cada carpeta raíz es una norma
    return root


@pytest.fixture
def service(migrated_engine: Engine, docs: Path) -> IngestionService:
    return IngestionService(migrated_engine, docs, ExtractionConfig())


@pytest.fixture
def db(migrated_engine: Engine) -> Callable[[], Session]:
    return make_session_factory(migrated_engine)


def write_pdf(root: Path, name: str, refs: list[str], *, folder: str = "A") -> Path:
    directory = root / folder
    directory.mkdir(parents=True, exist_ok=True)
    lines = [heading("1 OBJETIVO"), Line("Texto del objetivo."), heading("4 REFERENCIAS")]
    lines += [ref(code, "Documento citado") for code in refs]
    lines += [heading("5 HISTORIAL"), Line("01 Creación del documento")]
    return build_pdf(directory / name, [lines])


def references_of(db: Callable[[], Session], code: str) -> dict[str, int | None]:
    with db() as session:
        document = session.scalars(select(Document).where(Document.code == code)).one()
        return {r.target_code: r.target_document_id for r in document.outgoing_references}


def document(db: Callable[[], Session], code: str) -> Document:
    with db() as session:
        return session.scalars(select(Document).where(Document.code == code)).one()


def open_issue_types(db: Callable[[], Session], code: str | None = None) -> list[str]:
    with db() as session:
        query = select(QualityIssue.issue_type).where(QualityIssue.resolved_at.is_(None))
        if code:
            query = query.where(QualityIssue.code == code)
        return sorted(session.scalars(query))


# ----------------------------------------------------------------------------- ingesta básica


def test_full_ingest_creates_documents_references_and_pending(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    write_pdf(
        docs, "MC-SGG-435-23 Manual.pdf", ["PO-SGS-400", "ES-SGC-001"], folder="A/sub/carpeta"
    )
    write_pdf(docs, "PO-SGS-400-01 Política.pdf", [])

    report = service.ingest_path(docs, IngestOptions())

    assert report.status is RunStatus.COMPLETED
    assert report.count("created") == 2
    manual = document(db, "MC-SGG-435")
    assert manual.folder == "A/sub/carpeta"
    assert manual.file_path == "A/sub/carpeta/MC-SGG-435-23 Manual.pdf"
    assert manual.references_sha256 == manual.sha256
    refs = references_of(db, "MC-SGG-435")
    assert refs["PO-SGS-400"] == document(db, "PO-SGS-400").id
    assert refs["ES-SGC-001"] is None  # pendiente: el documento aún no existe


def test_pending_reference_resolved_when_target_arrives(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    write_pdf(docs, "MC-SGG-435-23 Manual.pdf", ["ES-SGC-001"])
    service.ingest_path(docs, IngestOptions())

    write_pdf(docs, "ES-SGC-001-03 Política de la Calidad.pdf", [])
    service.ingest_path(docs, INCREMENTAL)

    assert references_of(db, "MC-SGG-435")["ES-SGC-001"] == document(db, "ES-SGC-001").id


def test_unchanged_files_are_not_reprocessed(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    write_pdf(docs, "MC-SGG-435-23 Manual.pdf", ["PO-SGS-400"])
    service.ingest_path(docs, IngestOptions())
    before = document(db, "MC-SGG-435")

    report = service.ingest_path(docs, INCREMENTAL)

    assert report.count("skipped") == 1
    assert report.count("created", "updated") == 0
    assert document(db, "MC-SGG-435").last_run_id == before.last_run_id


def test_full_reingest_is_idempotent(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    write_pdf(docs, "MC-SGG-435-23 Manual.pdf", ["PO-SGS-400", "ES-SGC-001"])
    service.ingest_path(docs, IngestOptions())
    with db() as session:
        first = sorted(session.execute(select(DocumentReference.id, DocumentReference.target_code)))

    service.ingest_path(docs, IngestOptions())

    with db() as session:
        assert (
            sorted(session.execute(select(DocumentReference.id, DocumentReference.target_code)))
            == first
        )
    assert open_issue_types(db) == []


def test_changed_file_updates_only_its_own_relations(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    write_pdf(docs, "MC-SGG-435-23 Manual.pdf", ["PO-SGS-400", "ES-SGC-001", "AL-SGS-401"])
    write_pdf(docs, "PO-SGS-400-01 Política.pdf", ["ES-SGC-001"])
    service.ingest_path(docs, IngestOptions())
    with db() as session:
        kept_id = session.scalar(
            select(DocumentReference.id).where(DocumentReference.target_code == "PO-SGS-400")
        )

    write_pdf(docs, "MC-SGG-435-23 Manual.pdf", ["PO-SGS-400", "AL-SGS-401"])  # quita ES-SGC-001
    report = service.ingest_path(docs, INCREMENTAL)

    assert report.count("updated") == 1
    assert report.count("skipped") == 1
    assert set(references_of(db, "MC-SGG-435")) == {"PO-SGS-400", "AL-SGS-401"}
    assert set(references_of(db, "PO-SGS-400")) == {"ES-SGC-001"}  # el otro documento no cambia
    with db() as session:
        assert (
            session.scalar(
                select(DocumentReference.id).where(DocumentReference.target_code == "PO-SGS-400")
            )
            == kept_id
        )


def test_documents_without_section_are_nodes_without_issues(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    build_pdf(
        docs / "A" / "LC-SGSA-915-02 Tabla.pdf", [[heading("1 HISTORIAL"), heading("2 LISTADO")]]
    )
    write_pdf(docs, "MC-SGG-435-23 Manual.pdf", ["LC-SGSA-915"])

    service.ingest_path(docs, IngestOptions())

    listing = document(db, "LC-SGSA-915")
    assert listing.extraction_status is ExtractionStatus.NO_SECTION
    assert references_of(db, "MC-SGG-435")["LC-SGSA-915"] == listing.id
    assert open_issue_types(db) == []
    with db() as session:
        assert session.scalars(select(IngestionRun)).one().no_section_count == 1


# ----------------------------------------------------------------------------- fallas que preservan


@pytest.mark.parametrize(
    ("rewrite", "status", "issue"),
    [
        (
            lambda path: build_pdf(path, [[], []], scanned_pages={1, 2}),
            ExtractionStatus.REQUIRES_OCR,
            "requires_ocr",
        ),
        (
            lambda path: build_pdf(
                path, [[heading("4 REFERENCIAS"), ref("X-ABC-001"), Line("Prosa final")]]
            ),
            ExtractionStatus.NEEDS_REVIEW,
            "section_end_uncertain",
        ),
        (
            lambda path: build_pdf(path, [[heading("1 OBJETIVO"), Line("Sin sección")]]),
            ExtractionStatus.NO_SECTION,
            "section_lost",
        ),
        (lambda path: path.write_bytes(b"archivo roto"), ExtractionStatus.ERROR, "read_error"),
    ],
)
def test_failed_extraction_keeps_current_references(
    service: IngestionService,
    docs: Path,
    db: Callable[[], Session],
    rewrite: Callable[[Path], object],
    status: ExtractionStatus,
    issue: str,
) -> None:
    path = write_pdf(docs, "MC-SGG-435-23 Manual.pdf", ["PO-SGS-400", "ES-SGC-001"])
    service.ingest_path(docs, IngestOptions())

    rewrite(path)
    service.ingest_path(docs, INCREMENTAL)

    manual = document(db, "MC-SGG-435")
    assert manual.extraction_status is status
    assert set(references_of(db, "MC-SGG-435")) == {"PO-SGS-400", "ES-SGC-001"}
    assert manual.references_stale
    assert issue in open_issue_types(db)


def test_retry_failed_reprocesses_unchanged_failures(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    path = docs / "A" / "MC-SGG-435-23 Manual.pdf"
    build_pdf(path, [[heading("4 REFERENCIAS"), ref("PO-SGS-400"), Line("Prosa final")]])
    service.ingest_path(docs, IngestOptions())
    assert document(db, "MC-SGG-435").extraction_status is ExtractionStatus.NEEDS_REVIEW

    assert service.ingest_path(docs, INCREMENTAL).count("skipped") == 1
    assert (
        service.ingest_path(docs, IngestOptions(incremental=True, retry_failed=True)).count(
            "updated"
        )
        == 1
    )


def test_changed_extraction_rules_reprocess_unchanged_files(
    migrated_engine: Engine, service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    write_pdf(docs, "MC-SGG-435-23 Manual.pdf", ["PO-SGS-400"])
    service.ingest_path(docs, IngestOptions())
    default = ExtractionConfig()
    changed = IngestionService(
        migrated_engine, docs, ExtractionConfig(terminators=default.terminators | {"glosario"})
    )

    assert changed.ingest_path(docs, INCREMENTAL).count("updated") == 1
    assert document(db, "MC-SGG-435").extraction_fingerprint == changed.fingerprint
    assert changed.ingest_path(docs, INCREMENTAL).count("skipped") == 1


def test_documents_without_fingerprint_are_reprocessed_once(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    write_pdf(docs, "MC-SGG-435-23 Manual.pdf", ["PO-SGS-400"])
    service.ingest_path(docs, IngestOptions())
    with db() as session:  # como queda una base anterior a la migración 0005
        session.scalars(select(Document)).one().extraction_fingerprint = None
        session.commit()

    assert service.ingest_path(docs, INCREMENTAL).count("updated") == 1
    assert service.ingest_path(docs, INCREMENTAL).count("skipped") == 1


def test_persistence_failure_rolls_back_the_document(
    service: IngestionService,
    docs: Path,
    db: Callable[[], Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = write_pdf(docs, "MC-SGG-435-23 Manual.pdf", ["PO-SGS-400", "ES-SGC-001"])
    service.ingest_path(docs, IngestOptions())
    before = document(db, "MC-SGG-435")

    write_pdf(docs, path.name, ["AL-SGS-401"])

    def boom(*args: object, **kwargs: object) -> bool:
        raise RuntimeError("disco lleno")

    monkeypatch.setattr(sync, "replace_references", boom)
    report = service.ingest_path(docs, INCREMENTAL)

    after = document(db, "MC-SGG-435")
    assert report.status is RunStatus.COMPLETED_WITH_ERRORS
    assert report.files[0].action == "error"
    assert after.sha256 == before.sha256  # ni siquiera el hash cambió
    assert set(references_of(db, "MC-SGG-435")) == {"PO-SGS-400", "ES-SGC-001"}
    assert "sync_error" in open_issue_types(db)


# ----------------------------------------------------------------------------- identidad y archivos


def test_newest_edition_wins_within_a_batch(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    write_pdf(docs, "PO-SGS-400-01 Política.pdf", ["ES-SGC-001"], folder="A/a")
    write_pdf(docs, "PO-SGS-400-02 Política.pdf", ["AL-SGS-401"], folder="A/b")

    report = service.ingest_path(docs, IngestOptions())

    assert sorted(f.action for f in report.files) == ["created", "superseded"]
    assert report.error_count == 0
    assert document(db, "PO-SGS-400").file_path == "A/b/PO-SGS-400-02 Política.pdf"
    assert set(references_of(db, "PO-SGS-400")) == {"AL-SGS-401"}
    assert open_issue_types(db) == ["superseded_version"]

    # Reingestar no cambia la elección (idempotente).
    again = service.ingest_path(docs, INCREMENTAL)
    assert sorted(f.action for f in again.files) == ["skipped", "superseded"]
    assert open_issue_types(db) == ["superseded_version"]


def test_newer_edition_replaces_the_registered_one(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    write_pdf(docs, "PO-SGS-400-01 Política.pdf", ["ES-SGC-001"], folder="A/a")
    service.ingest_path(docs, IngestOptions())
    original_id = document(db, "PO-SGS-400").id

    write_pdf(docs, "PO-SGS-400-02 Política.pdf", ["AL-SGS-401"], folder="A/b")
    report = service.ingest_path(docs, INCREMENTAL)

    current = document(db, "PO-SGS-400")
    assert current.id == original_id  # el mismo documento, ahora apuntando a la edición nueva
    assert (current.file_path, current.version) == ("A/b/PO-SGS-400-02 Política.pdf", "02")
    assert set(references_of(db, "PO-SGS-400")) == {"AL-SGS-401"}
    assert report.error_count == 0
    assert open_issue_types(db) == ["superseded_version"]


def test_older_edition_added_later_does_not_replace_the_current_one(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    write_pdf(docs, "PO-SGS-400-02 Política.pdf", ["AL-SGS-401"], folder="A/b")
    service.ingest_path(docs, IngestOptions())

    older = write_pdf(docs, "PO-SGS-400-01 Política.pdf", ["ES-SGC-001"], folder="A/a")
    os.utime(older, (946684800, 946684800))  # 2000-01-01: más vieja también por fecha
    report = service.ingest_path(docs, INCREMENTAL)

    assert [f.action for f in report.files if f.action != "skipped"] == ["superseded"]
    assert document(db, "PO-SGS-400").file_path == "A/b/PO-SGS-400-02 Política.pdf"


def test_version_and_date_in_disagreement_block_the_new_edition(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    write_pdf(docs, "PO-SGS-400-02 Política.pdf", ["AL-SGS-401"], folder="A/b")
    service.ingest_path(docs, IngestOptions())

    write_pdf(docs, "PO-SGS-400-01 Política.pdf", ["ES-SGC-001"], folder="A/a")  # v01 más reciente
    report = service.ingest_path(docs, INCREMENTAL)

    assert [f.action for f in report.files if f.action != "skipped"] == ["blocked"]
    assert document(db, "PO-SGS-400").file_path == "A/b/PO-SGS-400-02 Política.pdf"  # sigue igual
    assert set(references_of(db, "PO-SGS-400")) == {"AL-SGS-401"}
    assert open_issue_types(db) == ["ambiguous_editions"]


def test_ambiguous_periodic_editions_publish_nothing(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    old_high = docs / "A" / "ES-SGS-525 Informe - Marzo 2024.pdf"
    build_pdf(
        old_high,
        [
            [
                Line("Referencia/Versión : ES-SGS-525/04"),
                heading("4 REFERENCIAS"),
                heading("5 HISTORIAL"),
            ]
        ],
    )
    os.utime(old_high, (1710000000, 1710000000))
    new_low = docs / "A" / "ES-SGS-525 Informe - Marzo 2026.pdf"
    build_pdf(
        new_low,
        [
            [
                Line("Referencia/Versión : ES-SGS-525/01"),
                heading("4 REFERENCIAS"),
                heading("5 HISTORIAL"),
            ]
        ],
    )

    report = service.ingest_path(docs, IngestOptions())

    assert sorted(f.action for f in report.files) == ["blocked", "blocked"]
    assert report.status is RunStatus.COMPLETED_WITH_ERRORS
    with db() as session:
        assert session.scalars(select(Document)).all() == []
    assert open_issue_types(db) == ["ambiguous_editions", "ambiguous_editions"]


def test_identical_copy_in_another_folder_is_recognized(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    original = write_pdf(docs, "LC-SGS-100-13 Listado.pdf", [], folder="A/x")
    (docs / "A" / "y").mkdir()
    (docs / "A" / "y" / original.name).write_bytes(original.read_bytes())

    report = service.ingest_path(docs, IngestOptions())

    assert sorted(f.action for f in report.files) == ["created", "superseded"]
    assert open_issue_types(db) == ["duplicate_copy"]


def test_pdf_wins_over_word_source_of_the_same_document(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    build_docx(
        docs / "A" / "PO-SGS-400-01 Política.docx",
        [Heading("REFERENCIAS"), Para("[AL-SGS-401] Alcance"), Heading("HISTORIAL")],
    )
    write_pdf(docs, "PO-SGS-400-01 Política.pdf", ["ES-SGC-001"])

    report = service.ingest_path(docs, IngestOptions())

    assert sorted(f.action for f in report.files) == ["created", "superseded"]
    assert document(db, "PO-SGS-400").file_path == "A/PO-SGS-400-01 Política.pdf"
    assert report.error_count == 0
    assert open_issue_types(db) == ["alternate_format"]


def test_moved_file_keeps_the_document_and_its_relations(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    path = write_pdf(docs, "PO-SGS-400-01 Política.pdf", ["ES-SGC-001"], folder="A/viejo")
    service.ingest_path(docs, IngestOptions())
    original_id = document(db, "PO-SGS-400").id

    (docs / "A" / "nuevo").mkdir()
    path.rename(docs / "A" / "nuevo" / path.name)
    report = service.ingest_path(docs, INCREMENTAL)

    moved = document(db, "PO-SGS-400")
    assert moved.id == original_id
    assert moved.file_path == "A/nuevo/PO-SGS-400-01 Política.pdf"
    assert report.missing == []
    assert "file_moved" in open_issue_types(db)


def test_deleted_file_deactivates_document_and_pends_incoming(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    write_pdf(docs, "MC-SGG-435-23 Manual.pdf", ["PO-SGS-400"])
    policy = write_pdf(docs, "PO-SGS-400-01 Política.pdf", [])
    service.ingest_path(docs, IngestOptions())

    policy.unlink()
    report = service.ingest_path(docs, INCREMENTAL)

    assert report.missing == ["A/PO-SGS-400"]
    assert not document(db, "PO-SGS-400").is_active
    assert references_of(db, "MC-SGG-435")["PO-SGS-400"] is None
    assert "file_missing" in open_issue_types(db)

    with db() as session, session.begin():
        assert prune_missing(session) == ["A/PO-SGS-400"]
    with db() as session:
        assert session.scalar(select(Document).where(Document.code == "PO-SGS-400")) is None


def test_missing_files_only_marked_when_scanning_the_root(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    write_pdf(docs, "PO-SGS-400-01 Política.pdf", [], folder="A/a")
    write_pdf(docs, "ES-SGC-001-01 Calidad.pdf", [], folder="A/b")
    service.ingest_path(docs, IngestOptions())

    report = service.ingest_path(docs / "A" / "a", IngestOptions())

    assert report.missing == []
    assert document(db, "ES-SGC-001").is_active


def test_code_change_at_same_path_requires_replace(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    path = docs / "A" / "documento.pdf"
    write_pdf(docs, "documento.pdf", ["ES-SGC-001"])
    service.ingest_file(path, IngestOptions(code_override="PO-SGS-400"))

    blocked = service.ingest_file(path, IngestOptions(code_override="PO-SGS-401"))
    assert blocked.files[0].action == "blocked"
    assert document(db, "PO-SGS-400").is_active

    replaced = service.ingest_file(path, IngestOptions(code_override="PO-SGS-401", replace=True))
    assert replaced.files[0].action == "created"
    with db() as session:
        assert session.scalar(select(Document).where(Document.code == "PO-SGS-400")) is None


def test_unresolved_source_code_creates_no_document(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    write_pdf(docs, "sin código.pdf", ["ES-SGC-001"])

    report = service.ingest_path(docs, IngestOptions())

    assert report.files[0].action == "unpublished"
    assert report.status is RunStatus.COMPLETED_WITH_ERRORS
    with db() as session:
        assert session.scalars(select(Document)).all() == []
    assert open_issue_types(db) == ["source_code_missing"]


def test_reprocessing_closes_previous_issues(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    path = docs / "A" / "PO-SGS-400-01 Política.pdf"
    build_pdf(path, [[heading("4 REFERENCIAS"), Line("[ES-SG-1] mal"), heading("5 HISTORIAL")]])
    service.ingest_path(docs, IngestOptions())
    assert open_issue_types(db) == ["invalid_reference_candidate"]

    write_pdf(docs, path.name, ["ES-SGC-001"])
    service.ingest_path(docs, INCREMENTAL)

    assert open_issue_types(db) == []


# ----------------------------------------------------------------------------- corrida


def test_ignored_and_unsupported_files(service: IngestionService, docs: Path) -> None:
    write_pdf(docs, "PO-SGS-400-01 Política.pdf", [])
    (docs / "A" / "~$-SGS-400-01 Política.docx").write_bytes(b"bloqueo de Word")
    (docs / "A" / "Inducción.pptx").write_bytes(b"x")
    (docs / "A" / ".oculto").mkdir()
    write_pdf(docs, "ES-SGC-001-01 Oculto.pdf", [], folder="A/.oculto")

    report = service.ingest_path(docs, IngestOptions())

    assert [f.code for f in report.files] == ["PO-SGS-400"]
    assert report.unsupported_count == 1


def test_path_outside_documents_dir_is_rejected(service: IngestionService, tmp_path: Path) -> None:
    outside = tmp_path / "fuera"
    outside.mkdir()

    with pytest.raises(PathOutsideRootError):
        service.ingest_path(outside, IngestOptions())
    with pytest.raises(PathOutsideRootError):
        service.ingest_path(tmp_path / "documents" / ".." / "fuera", IngestOptions())


def test_ingest_file_rejects_unsupported(service: IngestionService, docs: Path) -> None:
    other = docs / "A" / "plantilla.dotx"
    other.write_bytes(b"x")

    with pytest.raises(UnsupportedFileError):
        service.ingest_file(other, IngestOptions())


def test_ingest_file_always_reprocesses(service: IngestionService, docs: Path) -> None:
    path = write_pdf(docs, "PO-SGS-400-01 Política.pdf", [])
    service.ingest_path(docs, IngestOptions())

    report = service.ingest_file(path, IngestOptions())

    assert report.files[0].action == "updated"


def test_dry_run_writes_nothing(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    write_pdf(docs, "PO-SGS-400-01 Política.pdf", ["ES-SGC-001"])

    report = service.ingest_path(docs, IngestOptions(dry_run=True))

    assert [(f.action, f.code, f.references) for f in report.files] == [
        ("planned", "PO-SGS-400", 1)
    ]
    with db() as session:
        assert session.scalars(select(IngestionRun)).all() == []
        assert session.scalars(select(Document)).all() == []


def test_concurrent_run_is_locked_unless_forced(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    with db() as session, session.begin():
        session.add(IngestionRun(mode="full", root_path="x", status=RunStatus.RUNNING))

    with pytest.raises(IngestionLockedError):
        service.ingest_path(docs, IngestOptions())

    report = service.ingest_path(docs, IngestOptions(force_unlock=True))
    assert report.status is RunStatus.COMPLETED
    with db() as session:
        assert session.get(IngestionRun, 1).status is RunStatus.INTERRUPTED


def test_run_counters(service: IngestionService, docs: Path, db: Callable[[], Session]) -> None:
    write_pdf(docs, "PO-SGS-400-01 Política.pdf", ["ES-SGC-001"])
    build_pdf(docs / "A" / "LC-SGSA-915-02 Tabla.pdf", [[heading("1 LISTADO")]])
    (docs / "A" / "x.dotx").write_bytes(b"x")
    service.ingest_path(docs, IngestOptions())
    service.ingest_path(docs, INCREMENTAL)

    with db() as session:
        first, second = session.scalars(select(IngestionRun).order_by(IngestionRun.id)).all()
    assert (first.processed_count, first.new_count, first.no_section_count) == (2, 2, 1)
    assert first.unsupported_skipped_count == 1
    assert (second.processed_count, second.skipped_count) == (0, 2)
    assert first.status is second.status is RunStatus.COMPLETED
    assert first.ended_at is not None


# ----------------------------------------------------------------------------- grafo único y normas


def references_by_norma(db: Callable[[], Session], norma: str, code: str) -> dict[str, str | None]:
    """Referencias de ``norma/code`` con la norma del destino (None si está pendiente)."""
    with db() as session:
        source = session.scalars(
            select(Document).where(Document.norma == norma, Document.code == code)
        ).one()
        return {
            r.target_code: r.target_document.norma if r.target_document else None
            for r in source.outgoing_references
        }


def test_same_code_in_two_normas_is_two_documents(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    write_pdf(docs, "MC-SGG-435-23 Manual.pdf", ["PO-SGS-400"], folder="A")
    write_pdf(docs, "MC-SGG-435-23 Manual.pdf", ["ES-SGC-001"], folder="B")
    write_pdf(docs, "PO-SGS-400-01 Política.pdf", [], folder="B")

    report = service.ingest_path(docs, IngestOptions())

    assert report.count("created") == 3
    assert report.count("blocked") == 0  # el mismo código en dos normas no es duplicado
    with db() as session:
        manuals = session.scalars(select(Document).where(Document.code == "MC-SGG-435")).all()
        assert sorted(d.norma for d in manuals) == ["A", "B"]
    # PO-SGS-400 existe solo en B: la referencia de A se resuelve entre normas.
    assert references_by_norma(db, "A", "MC-SGG-435") == {"PO-SGS-400": "B"}
    assert report.graph_state is not None and report.graph_state.cross_norma == 1


def test_reference_prefers_the_same_norma(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    write_pdf(docs, "MC-SGG-435-23 Manual.pdf", ["ES-SGC-001"], folder="A")
    write_pdf(docs, "ES-SGC-001-01 Calidad.pdf", [], folder="A")
    write_pdf(docs, "ES-SGC-001-01 Calidad.pdf", [], folder="B")

    service.ingest_path(docs, IngestOptions())

    assert references_by_norma(db, "A", "MC-SGG-435") == {"ES-SGC-001": "A"}


def test_pending_reference_is_resolved_across_normas_and_rebound_to_its_own_norma(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    write_pdf(docs, "MC-SGG-435-23 Manual.pdf", ["ES-SGC-001"], folder="A")
    service.ingest_path(docs, IngestOptions())
    assert references_by_norma(db, "A", "MC-SGG-435") == {"ES-SGC-001": None}

    write_pdf(docs, "ES-SGC-001-03 Calidad.pdf", [], folder="B")
    report = service.ingest_path(docs, INCREMENTAL)
    assert references_by_norma(db, "A", "MC-SGG-435") == {"ES-SGC-001": "B"}
    assert report.unresolved_count == 0

    write_pdf(docs, "ES-SGC-001-03 Calidad.pdf", [], folder="A")
    service.ingest_path(docs, INCREMENTAL)
    assert references_by_norma(db, "A", "MC-SGG-435") == {"ES-SGC-001": "A"}


def test_reference_to_a_code_in_several_other_normas_stays_pending(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    write_pdf(docs, "MC-SGG-435-23 Manual.pdf", ["ES-SGC-001"], folder="C")
    write_pdf(docs, "ES-SGC-001-01 Calidad.pdf", [], folder="A")
    in_b = write_pdf(docs, "ES-SGC-001-01 Calidad.pdf", [], folder="B")

    report = service.ingest_path(docs, IngestOptions())

    assert references_by_norma(db, "C", "MC-SGG-435") == {"ES-SGC-001": None}
    assert report.graph_state is not None and report.graph_state.ambiguous == 1

    # Si desaparece una de las dos copias, la referencia pasa a la única que queda.
    in_b.unlink()
    service.ingest_path(docs, INCREMENTAL)
    assert references_by_norma(db, "C", "MC-SGG-435") == {"ES-SGC-001": "A"}


def test_deleted_target_falls_back_to_the_copy_in_another_norma(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    write_pdf(docs, "MC-SGG-435-23 Manual.pdf", ["ES-SGC-001"], folder="A")
    own = write_pdf(docs, "ES-SGC-001-01 Calidad.pdf", [], folder="A")
    write_pdf(docs, "ES-SGC-001-01 Calidad.pdf", [], folder="B")
    service.ingest_path(docs, IngestOptions())

    own.unlink()
    service.ingest_path(docs, INCREMENTAL)

    assert references_by_norma(db, "A", "MC-SGG-435") == {"ES-SGC-001": "B"}


def test_loose_files_in_the_root_are_ignored_and_reported(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    write_pdf(docs, "PO-SGS-400-01 Política.pdf", [], folder="")
    write_pdf(docs, "ES-SGC-001-01 Calidad.pdf", [])

    report = service.ingest_path(docs, IngestOptions())

    assert report.root_files == ["PO-SGS-400-01 Política.pdf"]
    assert [f.code for f in report.files] == ["ES-SGC-001"]
    with db() as session:
        assert session.scalars(select(IngestionRun)).one().root_files_count == 1
    with pytest.raises(UnsupportedFileError, match="suelto en la raíz"):
        service.ingest_file(docs / "PO-SGS-400-01 Política.pdf", IngestOptions())


def test_moving_a_file_to_another_norma_creates_a_new_document(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    write_pdf(docs, "MC-SGG-435-23 Manual.pdf", ["PO-SGS-400"], folder="A")
    path = write_pdf(docs, "PO-SGS-400-01 Política.pdf", ["ES-SGC-001"], folder="A")
    service.ingest_path(docs, IngestOptions())

    (docs / "B").mkdir()
    path.rename(docs / "B" / path.name)
    report = service.ingest_path(docs, INCREMENTAL)

    assert report.missing == ["A/PO-SGS-400"]
    with db() as session:
        documents = session.scalars(select(Document).where(Document.code == "PO-SGS-400")).all()
        assert sorted((d.norma, d.is_active) for d in documents) == [("A", False), ("B", True)]
    # Quien lo citaba sigue la nueva ubicación (otra norma).
    assert references_by_norma(db, "A", "MC-SGG-435") == {"PO-SGS-400": "B"}


# ----------------------------------------------------------------------------- planillas XLSX


def test_spreadsheet_is_a_node_that_can_be_cited(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    write_pdf(docs, "PO-SGS-400-01 Política.pdf", ["RG-SGSA-927"])
    build_xlsx(docs / "B" / "RG-SGSA-927-02 Inventario.xlsx", title="Inventario de activos")

    report = service.ingest_path(docs, IngestOptions())

    sheet = document(db, "RG-SGSA-927")
    assert (sheet.file_format, sheet.extraction_status) == (
        FileFormat.XLSX,
        ExtractionStatus.NOT_APPLICABLE,
    )
    assert (sheet.version, sheet.title) == ("02", "Inventario")
    assert references_of(db, "RG-SGSA-927") == {}
    assert references_by_norma(db, "A", "PO-SGS-400") == {"RG-SGSA-927": "B"}
    assert open_issue_types(db, "RG-SGSA-927") == []
    assert report.error_count == 0


def test_xlsm_and_legacy_xls_are_citable_spreadsheets(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    write_pdf(docs, "PO-SGS-400-01 Política.pdf", ["RG-SGSA-930", "RG-SGSA-931"])
    build_xlsx(docs / "A" / "RG-SGSA-930-01 Con macros.xlsm")
    (docs / "A" / "RG-SGSA-931-01 Antigua.xls").write_bytes(
        bytes.fromhex("D0CF11E0A1B11AE1") + bytes(512)
    )

    report = service.ingest_path(docs, IngestOptions())

    assert report.error_count == 0
    assert [
        (document(db, code).file_format, document(db, code).extraction_status)
        for code in ("RG-SGSA-930", "RG-SGSA-931")
    ] == [
        (FileFormat.XLSM, ExtractionStatus.NOT_APPLICABLE),
        (FileFormat.XLS, ExtractionStatus.NOT_APPLICABLE),
    ]
    assert references_by_norma(db, "A", "PO-SGS-400") == {"RG-SGSA-930": "A", "RG-SGSA-931": "A"}


def test_spreadsheet_code_from_custom_property(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    build_xlsx(docs / "A" / "inventario.xlsx", custom_properties={"Referencia": "RG-SGSA-927"})

    service.ingest_path(docs, IngestOptions())

    # Una sola fuente de contenido no alcanza para fijar el código (como en DOCX).
    assert open_issue_types(db) == ["source_code_missing"]

    build_xlsx(
        docs / "A" / "RG-SGSA-927 inventario.xlsx", custom_properties={"Referencia": "RG-SGSA-927"}
    )
    service.ingest_path(docs, IngestOptions())
    assert document(db, "RG-SGSA-927").code_source == "filename+content"


def test_unreadable_spreadsheet_is_reported(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    (docs / "A" / "RG-SGSA-927-01 Inventario.xlsx").write_bytes(b"no es un zip")

    report = service.ingest_path(docs, IngestOptions())

    assert [(f.action, f.status) for f in report.files] == [("unpublished", ExtractionStatus.ERROR)]
    assert open_issue_types(db) == ["read_error"]


def test_pdf_wins_over_spreadsheet_of_the_same_document(
    service: IngestionService, docs: Path, db: Callable[[], Session]
) -> None:
    write_pdf(docs, "RG-SGSA-927-01 Inventario.pdf", [])
    build_xlsx(docs / "A" / "RG-SGSA-927-01 Inventario.xlsx")

    report = service.ingest_path(docs, IngestOptions())

    assert {f.rel_path: f.action for f in report.files} == {
        "A/RG-SGSA-927-01 Inventario.pdf": "created",
        "A/RG-SGSA-927-01 Inventario.xlsx": "superseded",
    }
    assert document(db, "RG-SGSA-927").file_format is FileFormat.PDF
