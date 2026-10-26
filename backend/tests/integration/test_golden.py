"""Set de referencia: formato, métricas y comandos ``golden draft`` / ``golden evaluate``."""

import csv
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.cli import app
from app.ingestion.extractor import extract_document
from app.services import golden
from tests.fixtures.builders import Line, build_pdf, heading, ref

runner = CliRunner()


def write_pdf(path: Path, lines: list[Line]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    build_pdf(path, [lines])


@pytest.fixture
def samples(tmp_path: Path) -> Path:
    root = tmp_path / "samples"
    write_pdf(
        root / "A" / "MC-SGG-435-23 Manual.pdf",
        [
            heading("4 REFERENCIAS"),
            ref("ES-SGC-001"),
            ref("PO-SGS-400"),
            Line("Procedimientos", bold=True),
            ref("PR-SGG-101"),
            heading("5 HISTORIAL"),
        ],
    )
    write_pdf(root / "A" / "LC-SGC-500-01 Listado.pdf", [heading("1 HISTORIAL"), Line("Texto")])
    # Sin terminador: la sección no se puede delimitar con certeza.
    write_pdf(
        root / "A" / "PO-SGS-400-01 Politica.pdf", [heading("4 REFERENCIAS"), ref("AX-SGC-001")]
    )
    return root


def write_golden(path: Path, rows: list[tuple[str, str, str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["file", "target_code", "group", "note"])
        writer.writerows([[*row, ""] for row in rows])
    return path


MANUAL = "A/MC-SGG-435-23 Manual.pdf"


def test_load_golden_groups_rows_by_file(tmp_path: Path) -> None:
    path = write_golden(
        tmp_path / "g.csv",
        [
            (MANUAL, "es-sgc-001", "general"),
            (MANUAL, "PR-SGG-101", "procedimientos"),
            ("A\\x.pdf", "", ""),
        ],
    )

    assert golden.load_golden(path) == {
        MANUAL: {"ES-SGC-001": "general", "PR-SGG-101": "procedimientos"},
        "A/x.pdf": {},
    }


def test_load_golden_rejects_missing_columns(tmp_path: Path) -> None:
    path = tmp_path / "g.csv"
    path.write_text("archivo;codigo\n", encoding="utf-8")

    with pytest.raises(golden.GoldenFormatError, match="file, target_code"):
        golden.load_golden(path)


def test_evaluate_counts_hits_misses_and_extras(samples: Path, tmp_path: Path) -> None:
    expected = golden.load_golden(
        write_golden(
            tmp_path / "g.csv",
            [
                (MANUAL, "ES-SGC-001", "general"),
                (MANUAL, "PR-SGG-101", "general"),  # grupo mal anotado a propósito
                (MANUAL, "LC-SGC-500", "general"),  # falta en el documento
                ("A/LC-SGC-500-01 Listado.pdf", "", ""),
                ("A/PO-SGS-400-01 Politica.pdf", "AX-SGC-001", "general"),
                ("A/no-existe.pdf", "ES-SGC-001", "general"),
            ],
        )
    )
    report = golden.evaluate(expected, samples, extract_document)
    by_file = {f.file: f for f in report.files}

    manual = by_file[MANUAL]
    assert manual.false_positives == {"PO-SGS-400"}
    assert manual.false_negatives == {"LC-SGC-500"}
    assert manual.group_mismatches == {"PR-SGG-101"}
    # Sección sin fin claro: no se publicaría nada, así que cuenta como no encontrada.
    assert by_file["A/PO-SGS-400-01 Politica.pdf"].status == "needs_review"
    assert by_file["A/PO-SGS-400-01 Politica.pdf"].false_negatives == {"AX-SGC-001"}
    assert by_file["A/no-existe.pdf"].status == "missing_file"
    assert (report.true_positives, report.false_positives, report.false_negatives) == (2, 1, 3)
    assert report.precision == pytest.approx(2 / 3)
    assert report.recall == pytest.approx(2 / 5)
    assert report.group_accuracy == pytest.approx(0.5)
    assert not report.meets(0.99, 0.98)


def test_empty_report_is_perfect() -> None:
    report = golden.GoldenReport()

    assert (report.precision, report.recall, report.group_accuracy) == (1.0, 1.0, 1.0)


def test_draft_then_evaluate_round_trip(samples: Path, tmp_path: Path) -> None:
    draft = tmp_path / "golden" / "expected.csv"

    created = runner.invoke(app, ["golden", "draft", str(samples), "-o", str(draft)])
    rows = list(csv.DictReader(draft.open(encoding="utf-8-sig"), delimiter=";"))
    evaluated = runner.invoke(app, ["golden", "evaluate", str(draft), "--samples", str(samples)])

    assert created.exit_code == 0, created.output
    assert "1 filas marcadas REVISAR" in created.output
    assert {(r["target_code"], r["group"]) for r in rows if r["file"] == MANUAL} == {
        ("ES-SGC-001", "general"),
        ("PO-SGS-400", "general"),
        ("PR-SGG-101", "procedimientos"),
    }
    assert any(r["note"] == "sin referencias" for r in rows)
    # Sin corregir, el borrador coincide con la extracción salvo lo que hay que revisar.
    assert evaluated.exit_code == 1
    assert "faltan AX-SGC-001" in evaluated.output
    assert "precisión 100.00%" in evaluated.output


def test_draft_never_overwrites_an_annotated_set(samples: Path, tmp_path: Path) -> None:
    existing = tmp_path / "expected.csv"
    existing.write_text("anotado a mano", encoding="utf-8")

    result = runner.invoke(app, ["golden", "draft", str(samples), "-o", str(existing)])

    assert result.exit_code == 2
    assert existing.read_text(encoding="utf-8") == "anotado a mano"


def test_evaluate_passes_with_a_corrected_set(samples: Path, tmp_path: Path) -> None:
    path = write_golden(
        tmp_path / "g.csv",
        [
            (MANUAL, "ES-SGC-001", "general"),
            (MANUAL, "PO-SGS-400", "general"),
            (MANUAL, "PR-SGG-101", "procedimientos"),
            ("A/LC-SGC-500-01 Listado.pdf", "", ""),
        ],
    )

    result = runner.invoke(app, ["golden", "evaluate", str(path), "--samples", str(samples)])

    assert result.exit_code == 0, result.output
    assert "recall 100.00%" in result.output
