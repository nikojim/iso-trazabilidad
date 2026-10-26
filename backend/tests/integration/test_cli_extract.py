import json
from pathlib import Path

from typer.testing import CliRunner

from app.cli import app
from tests.fixtures.builders import MANUAL_HEADER, build_pdf, manual_pages

runner = CliRunner()


def _manual(tmp_path: Path) -> Path:
    return build_pdf(
        tmp_path / "MC-SGG-435-23 Manual de los Sistemas de Gestión.pdf",
        manual_pages(),
        header=MANUAL_HEADER,
    )


def test_extract_json(tmp_path: Path) -> None:
    result = runner.invoke(app, ["extract", "--json", str(_manual(tmp_path))])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["source_code"] == "MC-SGG-435"
    assert payload["status"] == "ok"
    assert payload["occurrence_count"] == 36
    assert len(payload["references"]) == 35


def test_extract_summary(tmp_path: Path) -> None:
    result = runner.invoke(app, ["extract", str(_manual(tmp_path))])

    assert result.exit_code == 0, result.output
    assert "35 únicas, 36 apariciones" in result.output
    assert "PR-SGG-101" in result.output


def test_extract_unreadable_file_exits_with_error(tmp_path: Path) -> None:
    broken = tmp_path / "PO-SGS-400-01 Roto.pdf"
    broken.write_bytes(b"basura")

    result = runner.invoke(app, ["extract", str(broken)])

    assert result.exit_code == 1
    assert "read_error" in result.output


def test_extract_uses_configured_aliases(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    config = tmp_path / "extraction.toml"
    config.write_text('[referencias]\nsection_aliases = ["Documentos de referencia"]\n', "utf-8")
    monkeypatch.setenv("ISO_EXTRACTION_CONFIG", str(config))
    from tests.fixtures.builders import heading, ref

    pdf = build_pdf(
        tmp_path / "PO-SGS-400-01 Política.pdf",
        [[heading("4 DOCUMENTOS DE REFERENCIA"), ref("ES-SGC-001"), heading("5 HISTORIAL")]],
    )

    result = runner.invoke(app, ["extract", "--json", str(pdf)])

    assert json.loads(result.output)["status"] == "ok"
