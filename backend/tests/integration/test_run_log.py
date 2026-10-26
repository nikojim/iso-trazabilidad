"""Log de cada corrida de ingesta: totales, documentos, duplicados y errores."""

from pathlib import Path

import pytest
from sqlalchemy import Engine, select

from app.db.session import make_session_factory
from app.ingestion.config import ExtractionConfig
from app.models import IngestionRun, RunStatus
from app.services import ingest as ingest_module
from app.services.ingest import IngestionService, IngestOptions
from tests.fixtures.builders import build_pdf, build_xlsx, heading, ref


def write_pdf(path: Path, refs: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [heading("4 REFERENCIAS"), *(ref(code) for code in refs), heading("5 HISTORIAL")]
    return build_pdf(path, [lines])


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    root = tmp_path / "documents"
    # MC cita dos veces a PO (duplicado), a ES (pendiente) y a la planilla de otra norma.
    write_pdf(
        root / "A" / "MC-SGG-435-23 Manual.pdf",
        ["PO-SGS-400", "PO-SGS-400", "ES-SGC-001", "RG-SGSA-927"],
    )
    write_pdf(root / "A" / "PO-SGS-400-01 Política.pdf", [])
    build_xlsx(root / "B" / "RG-SGSA-927-01 Inventario.xlsx")
    (root / "B" / "PR-SGG-101-01 Roto.pdf").write_bytes(b"no es un PDF")
    write_pdf(root / "suelto.pdf", [])
    return root


@pytest.fixture
def service(migrated_engine: Engine, docs: Path, tmp_path: Path) -> IngestionService:
    return IngestionService(
        migrated_engine, docs, ExtractionConfig(), log_dir=tmp_path / "logs", log_level="INFO"
    )


def lines_with(text: str, event: str) -> list[str]:
    return [line for line in text.splitlines() if f" {event} " in f"{line} "]


def test_run_log_documents_everything(
    service: IngestionService, docs: Path, migrated_engine: Engine
) -> None:
    report = service.ingest_path(docs, IngestOptions())

    assert report.log_path is not None
    text = Path(report.log_path).read_text("utf-8")
    assert Path(report.log_path).name.startswith(f"ingest-{report.run_id:05d}-")

    (start,) = lines_with(text, "inicio")
    assert "modo=full" in start
    (scan,) = lines_with(text, "escaneo")
    assert 'por_formato={"pdf": 3, "xlsx": 1}' in scan and "sueltos_en_raiz=1" in scan
    assert "archivo_sin_norma ruta=suelto.pdf" in text

    documents = lines_with(text, "documento")
    assert len(documents) == 4  # un renglón por archivo procesado
    manual = next(line for line in documents if "MC-SGG-435" in line)
    assert "accion=created" in manual and "referencias=3" in manual and "ocurrencias=4" in manual

    (duplicate,) = lines_with(text, "referencia_duplicada")
    assert "WARNING" in duplicate and "destino=PO-SGS-400 veces=2" in duplicate
    assert any("tipo=duplicate_in_section" in line for line in lines_with(text, "incidencia"))

    broken = next(line for line in documents if "PR-SGG-101" in line)
    assert broken.split()[2] == "ERROR" and "estado=error" in broken
    assert any("tipo=read_error" in line for line in lines_with(text, "incidencia"))

    # PO y la planilla de B llegaron después del manual: sus citas se resolvieron en la corrida.
    rebound = lines_with(text, "re_resolucion")
    assert [line.split(" re_resolucion ")[1] for line in rebound] == [
        "origen=A/MC-SGG-435 codigo=PO-SGS-400 antes=pendiente despues=A/PO-SGS-400",
        "origen=A/MC-SGG-435 codigo=RG-SGSA-927 antes=pendiente despues=B/RG-SGSA-927",
    ]

    (summary,) = lines_with(text, "resumen")
    for field in (
        "estado=completed_with_errors",
        "nuevos=3",
        "errores=1",
        "sueltos_en_raiz=1",
        "referencias=3",
        "ocurrencias=4",
        "duplicadas=1",
        "grafo_pendientes=1",
        "grafo_otra_norma=1",
    ):
        assert field in summary, field

    with make_session_factory(migrated_engine)() as session:
        run = session.scalars(select(IngestionRun)).one()
    assert run.status is RunStatus.COMPLETED_WITH_ERRORS
    assert (run.references_count, run.occurrences_count) == (3, 4)
    assert (run.duplicate_references_count, run.unresolved_count) == (1, 1)
    assert run.log_path == report.log_path


def test_unexpected_extraction_error_is_logged_with_traceback(
    service: IngestionService, docs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_extract = ingest_module.extract_document

    def flaky(path: Path, **kwargs: object):  # type: ignore[no-untyped-def]
        if path.name.startswith("PO-SGS-400"):
            raise RuntimeError("fallo inesperado del lector")
        return real_extract(path, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ingest_module, "extract_document", flaky)

    report = service.ingest_path(docs, IngestOptions())

    text = Path(report.log_path or "").read_text("utf-8")
    assert "error_extraccion" in text and "RuntimeError: fallo inesperado del lector" in text
    assert "Traceback" in text
    # Los demás documentos se publicaron igual.
    assert report.count("created") == 2
    assert next(f for f in report.files if f.rel_path.startswith("A/PO")).action == "unpublished"


def test_dry_run_is_logged_as_simulation(service: IngestionService, docs: Path) -> None:
    report = service.ingest_path(docs, IngestOptions(dry_run=True))

    assert report.log_path is not None and "ingest-simulacion-" in report.log_path
    text = Path(report.log_path).read_text("utf-8")
    assert "simulacion=True" in text and "accion=planned" in text
    assert "resumen estado=simulacion" in text


def test_incremental_run_logs_unchanged_files(service: IngestionService, docs: Path) -> None:
    service.ingest_path(docs, IngestOptions())
    report = service.ingest_path(docs, IngestOptions(incremental=True))

    text = Path(report.log_path or "").read_text("utf-8")
    assert len(lines_with(text, "sin_cambios")) == 3
    # El archivo ilegible nunca se publicó: se vuelve a intentar.
    assert any("PR-SGG-101" in line for line in lines_with(text, "extraido"))
