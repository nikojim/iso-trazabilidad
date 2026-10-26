from datetime import UTC, datetime

from app.models import FileFormat
from app.services.editions import Edition, choose_edition


def edition(
    path: str,
    version: str | None,
    year: int,
    *,
    sha: str | None = None,
    file_format: FileFormat = FileFormat.PDF,
) -> Edition:
    return Edition(path, version, file_format, datetime(year, 1, 1, tzinfo=UTC), sha or path)


def test_higher_version_that_is_also_newest_wins() -> None:
    choice = choose_edition(
        "PO-SGS-400", [edition("v1.pdf", "01", 2022), edition("v2.pdf", "02", 2024)]
    )

    assert choice.current.path == "v2.pdf"
    assert choice.issues["v1.pdf"].type == "superseded_version"


def test_periodic_reports_with_restarting_versions_are_ambiguous() -> None:
    # Caso real ES-SGS-525: Marzo 2024 es v04, pero Marzo 2026 (más reciente) es v01.
    choice = choose_edition(
        "ES-SGS-525",
        [
            edition("Abril 2022.pdf", "02", 2022),
            edition("Marzo 2024.pdf", "04", 2024),
            edition("Marzo 2026.pdf", "01", 2026),
        ],
    )

    assert choice.current is None
    assert {issue.type for issue in choice.issues.values()} == {"ambiguous_editions"}
    assert len(choice.issues) == 3
    assert [e["path"] for e in choice.issues["Marzo 2026.pdf"].details["editions"]] == [
        "Abril 2022.pdf",
        "Marzo 2024.pdf",
        "Marzo 2026.pdf",
    ]


def test_same_version_same_format_different_content_is_ambiguous() -> None:
    choice = choose_edition(
        "PO-SGS-400", [edition("a.pdf", "02", 2024), edition("b.pdf", "02", 2025)]
    )

    assert choice.current is None


def test_identical_copies_are_collapsed_before_choosing() -> None:
    choice = choose_edition(
        "LC-SGS-100",
        [edition("x/LC.pdf", "14", 2025, sha="same"), edition("y/LC.pdf", "14", 2025, sha="same")],
    )

    assert choice.current.path == "x/LC.pdf"
    assert choice.issues["y/LC.pdf"].type == "duplicate_copy"


def test_pdf_preferred_over_word_of_the_same_version() -> None:
    choice = choose_edition(
        "PO-SGS-400",
        [
            edition("p.docx", "03", 2025, file_format=FileFormat.DOCX),
            edition("p.pdf", "03", 2024),
        ],
    )

    assert choice.current.path == "p.pdf"
    assert choice.issues["p.docx"].type == "alternate_format"


def test_unknown_versions_fall_back_to_ambiguity() -> None:
    choice = choose_edition(
        "PO-SGS-400", [edition("a.pdf", None, 2024), edition("b.pdf", None, 2025)]
    )

    assert choice.current is None


def test_spreadsheet_loses_to_pdf_of_the_same_version() -> None:
    choice = choose_edition(
        "RG-SGSA-927",
        [
            edition("RG.xlsx", "01", 2024, file_format=FileFormat.XLSX),
            edition("RG.pdf", "01", 2024),
        ],
    )

    assert choice.current.path == "RG.pdf"
    assert choice.issues["RG.xlsx"].type == "alternate_format"
