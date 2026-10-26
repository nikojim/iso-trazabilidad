import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.cli import app
from tests.fixtures.builders import Line, build_pdf, heading, ref

runner = CliRunner()


@pytest.fixture
def env(tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    docs = tmp_path / "documents"
    (docs / "A").mkdir(parents=True)
    monkeypatch.setenv("ISO_DATABASE_URL", db_url)
    monkeypatch.setenv("ISO_DOCUMENTS_DIR", str(docs))
    assert runner.invoke(app, ["db", "init"]).exit_code == 0
    return docs


def write_pdf(path: Path, refs: list[str]) -> Path:
    lines = [heading("4 REFERENCIAS"), *(ref(code) for code in refs), heading("5 HISTORIAL")]
    return build_pdf(path, [lines])


def invoke(*args: str) -> str:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def test_ingest_incremental_and_queries(env: Path) -> None:
    write_pdf(env / "A" / "MC-SGG-435-23 Manual.pdf", ["PO-SGS-400", "ES-SGC-001"])
    write_pdf(env / "A" / "PO-SGS-400-01 Política.pdf", [])

    first = invoke("ingest")
    second = invoke("ingest", "--incremental")

    assert "nuevos 2" in first
    assert "created     MC-SGG-435" in first
    assert "sin cambios 2" in second
    stats = json.loads(invoke("stats"))
    assert stats["documents"] == 2
    assert stats["references"] == 2
    assert stats["unresolved_references"] == 1
    assert "completed" in invoke("runs", "list")


def test_validate_reports_pending_and_strict_mode(env: Path) -> None:
    write_pdf(env / "A" / "MC-SGG-435-23 Manual.pdf", ["ES-SGC-001"])
    invoke("ingest")

    table = invoke("validate")
    payload = json.loads(invoke("validate", "--format", "json"))

    assert "ES-SGC-001" in table
    assert payload["unresolved"] == {"ES-SGC-001": ["A/MC-SGG-435"]}
    assert runner.invoke(app, ["validate", "--strict"]).exit_code == 0


def test_validate_strict_fails_on_modified_file_and_open_errors(env: Path) -> None:
    path = write_pdf(env / "A" / "MC-SGG-435-23 Manual.pdf", ["ES-SGC-001"])
    write_pdf(env / "A" / "sin código.pdf", [])
    invoke("ingest")
    build_pdf(path, [[heading("4 REFERENCIAS"), ref("AL-SGS-401"), heading("5 HISTORIAL")]])

    payload = json.loads(invoke("validate", "--format", "json"))

    assert payload["hash_drift"] == ["A/MC-SGG-435"]
    assert "source_code_missing" in payload["open_issues"]
    assert runner.invoke(app, ["validate", "--strict"]).exit_code == 1


def test_issues_list(env: Path) -> None:
    build_pdf(
        env / "A" / "PO-SGS-400-01 Política.pdf",
        [[heading("4 REFERENCIAS"), Line("[ES-SG-1] mal"), heading("5 HISTORIAL")]],
    )
    invoke("ingest")

    output = invoke("issues", "list", "--type", "invalid_reference_candidate")

    assert "PO-SGS-400" in output
    assert "abierta" in output


def test_ingest_file_with_code_override(env: Path) -> None:
    path = write_pdf(env / "A" / "documento.pdf", ["ES-SGC-001"])

    output = invoke("ingest-file", str(path), "--code", "PO-SGS-400")

    assert "created     PO-SGS-400" in output


def test_prune_missing(env: Path) -> None:
    path = write_pdf(env / "A" / "PO-SGS-400-01 Política.pdf", [])
    invoke("ingest")
    path.unlink()
    assert "faltante    A/PO-SGS-400" in invoke("ingest")

    output = invoke("prune", "--missing", "--yes")

    assert "PO-SGS-400" in output
    assert json.loads(invoke("stats"))["inactive_documents"] == 0


def test_dry_run(env: Path) -> None:
    write_pdf(env / "A" / "PO-SGS-400-01 Política.pdf", ["ES-SGC-001"])

    output = invoke("ingest", "--dry-run")

    assert output.startswith("Simulación")
    assert json.loads(invoke("stats"))["documents"] == 0


def test_path_outside_documents_dir(env: Path, tmp_path: Path) -> None:
    result = runner.invoke(app, ["ingest", str(tmp_path)])

    assert result.exit_code == 2
    assert "fuera del directorio" in result.output


def test_commands_require_initialized_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ISO_DATABASE_URL", f"sqlite:///{(tmp_path / 'vacia.db').as_posix()}")

    result = runner.invoke(app, ["stats"])

    assert result.exit_code == 2
    assert "iso-trace db init" in result.output
