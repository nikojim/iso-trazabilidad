import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect

from app.db import migrate
from app.db.session import create_db_engine
from app.models import Base

EXPECTED_TABLES = {
    "alembic_version",
    "documents",
    "document_references",
    "reference_occurrences",
    "ingestion_runs",
    "quality_issues",
    "meta",
}


def _tables(db_url: str) -> set[str]:
    engine = create_db_engine(db_url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_creates_schema(db_url: str) -> None:
    migrate.upgrade(db_url)

    assert _tables(db_url) == EXPECTED_TABLES
    assert migrate.current_revision(db_url) == migrate.head_revision(db_url)


def test_upgrade_downgrade_upgrade(db_url: str) -> None:
    migrate.upgrade(db_url)
    migrate.downgrade(db_url, "base")
    assert _tables(db_url) == {"alembic_version"}

    migrate.upgrade(db_url)
    assert _tables(db_url) == EXPECTED_TABLES


def test_0002_assigns_graph_from_first_folder(db_url: str) -> None:
    from sqlalchemy import text

    migrate.upgrade(db_url, "0001")
    engine = create_db_engine(db_url)
    try:
        with engine.begin() as connection:
            for code, path in [("PO-SGS-400", "A/sub/x.pdf"), ("PO-SGS-401", "suelto.pdf")]:
                connection.execute(
                    text(
                        "INSERT INTO documents (code, document_type, system_code, file_path,"
                        " folder,"
                        " file_format, file_size, file_mtime, sha256, extraction_status, is_active,"
                        " metadata_json, first_seen_at, updated_at) VALUES (:code, 'PO', 'SGS',"
                        " :path, '', 'pdf', 1, '2026-01-01', 'x', 'ok', 1, '{}', '2026-01-01',"
                        " '2026-01-01')"
                    ),
                    {"code": code, "path": path},
                )
        migrate.upgrade(db_url, "0002")
        with engine.connect() as connection:
            rows = dict(connection.execute(text("SELECT code, graph_name FROM documents")).all())
    finally:
        engine.dispose()

    assert rows == {"PO-SGS-400": "A", "PO-SGS-401": ""}


_INSERT_0002 = (
    "INSERT INTO documents (id, graph_name, code, document_type, system_code, file_path, folder,"
    " file_format, file_size, file_mtime, sha256, extraction_status, is_active, metadata_json,"
    " first_seen_at, updated_at) VALUES (:id, :graph, :code, 'PO', 'SGS', :path, '', 'pdf', 1,"
    " '2026-01-01', 'x', 'ok', 1, '{}', '2026-01-01', '2026-01-01')"
)
_REFERENCE = (
    "INSERT INTO document_references (source_document_id, target_code, target_document_id,"
    " group_name, has_mixed_groups, occurrence_count, created_at, updated_at)"
    " VALUES (:source, :code, NULL, 'general', 0, 1, '2026-01-01', '2026-01-01')"
)


def test_0003_renames_to_norma_and_resolves_references_across_normas(db_url: str) -> None:
    from sqlalchemy import text

    migrate.upgrade(db_url, "0002")
    engine = create_db_engine(db_url)
    try:
        with engine.begin() as connection:
            documents = [
                (1, "A", "MC-SGG-435"),  # cita PO (solo en B), ES (en A y B) y LC (en B y C)
                (2, "B", "PO-SGS-400"),
                (3, "A", "ES-SGC-001"),
                (4, "B", "ES-SGC-001"),
                (5, "B", "LC-SGC-500"),
                (6, "C", "LC-SGC-500"),
            ]
            for doc_id, graph, code in documents:
                connection.execute(
                    text(_INSERT_0002),
                    {"id": doc_id, "graph": graph, "code": code, "path": f"{graph}/{code}.pdf"},
                )
            for code in ("PO-SGS-400", "ES-SGC-001", "LC-SGC-500"):
                connection.execute(text(_REFERENCE), {"source": 1, "code": code})
        migrate.upgrade(db_url)
        with engine.connect() as connection:
            normas = dict(connection.execute(text("SELECT id, norma FROM documents")).all())
            targets = dict(
                connection.execute(
                    text("SELECT target_code, target_document_id FROM document_references")
                ).all()
            )
    finally:
        engine.dispose()

    assert normas[1] == "A"
    # PO: única copia en otra norma; ES: la de la misma norma; LC: ambigua (B y C), pendiente.
    assert targets == {"PO-SGS-400": 2, "ES-SGC-001": 3, "LC-SGC-500": None}


def test_0003_downgrade_is_refused_with_spreadsheets(db_url: str, make_document) -> None:  # type: ignore[no-untyped-def]
    from app.db.session import make_session_factory
    from app.models import ExtractionStatus, FileFormat

    migrate.upgrade(db_url)
    engine = create_db_engine(db_url)
    try:
        with make_session_factory(engine)() as session, session.begin():
            session.add(
                make_document(
                    "RG-SGSA-927",
                    file_format=FileFormat.XLSX,
                    extraction_status=ExtractionStatus.NOT_APPLICABLE,
                )
            )
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="XLSX"):
        migrate.downgrade(db_url, "0002")


def test_0004_downgrade_is_refused_with_xls(db_url: str, make_document) -> None:  # type: ignore[no-untyped-def]
    from app.db.session import make_session_factory
    from app.models import ExtractionStatus, FileFormat

    migrate.upgrade(db_url)
    engine = create_db_engine(db_url)
    try:
        with make_session_factory(engine)() as session, session.begin():
            session.add(
                make_document(
                    "RG-SGSA-931",
                    file_format=FileFormat.XLS,
                    extraction_status=ExtractionStatus.NOT_APPLICABLE,
                )
            )
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="XLS"):
        migrate.downgrade(db_url, "0003")
    # 0005 se revierte; 0004 se niega y la base queda en esa revisión, sin perder planillas.
    assert migrate.current_revision(db_url) == "0004"


def test_orm_models_match_migrated_schema(db_url: str) -> None:
    migrate.upgrade(db_url)
    engine = create_db_engine(db_url)
    try:
        with engine.connect() as connection:
            diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    finally:
        engine.dispose()

    assert diff == []


def test_required_indexes_exist(db_url: str) -> None:
    migrate.upgrade(db_url)
    engine = create_db_engine(db_url)
    try:
        inspector = inspect(engine)
        doc_indexes = {ix["name"]: ix for ix in inspector.get_indexes("documents")}
        doc_uniques = inspector.get_unique_constraints("documents")
        ref_indexes = {ix["name"] for ix in inspector.get_indexes("document_references")}
        ref_uniques = inspector.get_unique_constraints("document_references")
    finally:
        engine.dispose()

    # El código es único por norma (carpeta raíz), no en toda la base.
    assert ["norma", "code"] in [u["column_names"] for u in doc_uniques]
    assert not doc_indexes["ix_documents_code"]["unique"]
    assert "ix_documents_norma" in doc_indexes
    assert "ix_document_references_target_code" in ref_indexes
    assert "ix_document_references_target_document_id" in ref_indexes
    # El índice único (source_document_id, target_code) cubre las búsquedas por origen.
    assert [u["column_names"] for u in ref_uniques] == [["source_document_id", "target_code"]]
