"""Resultados esperados sobre los documentos reales (docs/IMPLEMENTATION_PLAN.md §6.10).

Uso: ``ISO_REAL_SAMPLES_DIR=samples uv run pytest -m real_docs``. Los documentos son
confidenciales y nunca se versionan: sin la variable, estas pruebas se saltean.
"""

import os
from collections import Counter
from pathlib import Path

import pytest

from app.ingestion.extractor import extract_document
from app.ingestion.types import ExtractionResult
from app.models.enums import CodeSource, ExtractionStatus
from tests.fixtures.builders import ACCEPTANCE_GENERAL, ACCEPTANCE_PROCEDURES

pytestmark = pytest.mark.real_docs


@pytest.fixture(scope="module")
def samples_dir() -> Path:
    value = os.environ.get("ISO_REAL_SAMPLES_DIR")
    if not value or not Path(value).is_dir():
        pytest.skip("ISO_REAL_SAMPLES_DIR no está configurado")
    return Path(value)


@pytest.fixture(scope="module")
def extract(samples_dir: Path):  # type: ignore[no-untyped-def]
    cache: dict[str, ExtractionResult] = {}

    def by_code(code: str) -> ExtractionResult:
        if code not in cache:
            matches = sorted(
                path
                for path in samples_dir.rglob(f"{code}-*")
                if path.suffix.lower() in {".pdf", ".docx"} and not path.name.startswith("~$")
            )
            if not matches:
                pytest.skip(f"No está {code} en las muestras")
            cache[code] = extract_document(matches[0])
        return cache[code]

    return by_code


def codes(result: ExtractionResult) -> set[str]:
    return {ref.code for ref in result.references}


def test_manual_acceptance_case(extract) -> None:  # type: ignore[no-untyped-def]
    result = extract("MC-SGG-435")

    assert result.status is ExtractionStatus.OK
    assert (result.source_code, result.version) == ("MC-SGG-435", "23")
    assert result.code_source is CodeSource.FILENAME_AND_CONTENT
    assert result.occurrence_count == 36
    assert codes(result) == set(ACCEPTANCE_GENERAL) | set(ACCEPTANCE_PROCEDURES)
    assert Counter(ref.group for ref in result.references) == {"general": 27, "procedimientos": 8}
    assert len(next(r for r in result.references if r.code == "PR-SGG-101").occurrences) == 2
    assert (result.section.start_page, result.section.end_page) == (4, 5)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("AL-SGSA-911", {"ES-SGSA-919", "AC-SGSA-920", "ES-SGG-597"}),
        ("PO-SGSA-918", {"ES-SGG-597", "PR-AFP-200", "IN-AFP-203", "PC-SGSA-914"}),
        ("ES-SGSA-919", {"ES-SGG-597", "PR-AFP-100", "AC-AFP-698", "MC-SGG-435", "PC-SGSA-914"}),
        ("PO-SGSA-913", {"ES-SGG-597"}),
    ],
)
def test_reference_sets(extract, code: str, expected: set[str]) -> None:  # type: ignore[no-untyped-def]
    result = extract(code)

    assert result.status is ExtractionStatus.OK
    assert codes(result) == expected


def test_plan_with_pr_codes_and_no_subsection(extract) -> None:  # type: ignore[no-untyped-def]
    result = extract("PC-SGSA-914")

    assert result.status is ExtractionStatus.OK
    assert len(result.references) == 45
    assert {ref.group for ref in result.references} == {"general"}
    assert {"PR-SGG-000", "MC-SGG-435", "RG-SGSA-928"} <= codes(result)
    assert (result.section.start_page, result.section.end_page) == (4, 5)


@pytest.mark.parametrize(
    "code",
    ["LC-SGSA-915", "LC-SGSA-921", "LC-SGSA-922", "LC-SGSA-928", "ES-SGSA-923", "FC-SGSA-924"],
)
def test_documents_without_section_are_silent(extract, code: str) -> None:  # type: ignore[no-untyped-def]
    result = extract(code)

    assert result.status is ExtractionStatus.NO_SECTION
    assert result.source_code == code
    assert result.code_source is CodeSource.FILENAME_AND_CONTENT
    assert result.references == []
    assert [i for i in result.issues if i.severity != "info"] == []


def test_intentional_blank_page_is_not_ocr(extract) -> None:  # type: ignore[no-untyped-def]
    result = extract("PC-SGSA-936")

    assert result.status is ExtractionStatus.OK
    assert result.ocr_pages == []


def test_inconsistent_cited_titles_are_visible_in_hints(extract) -> None:  # type: ignore[no-untyped-def]
    manual = {r.code: r.title_hint for r in extract("MC-SGG-435").references}
    plan = {r.code: r.title_hint for r in extract("PC-SGSA-914").references}

    assert manual["ES-SGC-100"] == "Perfiles de Cargo Dirección de Tilsor"
    assert plan["ES-SGC-100"] == "Perfiles de Cargo Alta Gerencia"


# ----------------------------------------------------------------------------- Word (.docx)


def test_docx_section_saying_not_applicable_has_no_references(extract) -> None:  # type: ignore[no-untyped-def]
    result = extract("ES-AFP-201")

    assert result.status is ExtractionStatus.NO_REFERENCES
    assert result.section.terminator == "historial"
    assert result.references == []


@pytest.mark.parametrize("code", ["ES-SGC-003", "ES-SOP-001", "PC-COM-001"])
def test_docx_without_section_is_silent(extract, code: str) -> None:  # type: ignore[no-untyped-def]
    result = extract(code)

    assert result.status is ExtractionStatus.NO_SECTION
    assert result.source_code == code
    assert result.issues == []


def test_docx_reference_table_without_brackets(extract) -> None:  # type: ignore[no-untyped-def]
    result = extract("IN-SGC-001")

    assert [(r.code, r.title_hint) for r in result.references] == [
        ("ES-SGG-003", "Especificaciones de implementación CRM")
    ]
    assert "unbracketed_reference" in {i.type for i in result.issues}
    # El nombre dice IN-SGC-001 y el contenido IN-SGG-001: no se publica hasta corregirlo.
    assert result.status is ExtractionStatus.SOURCE_CODE_UNRESOLVED
    assert "source_code_conflict" in {i.type for i in result.issues}


def test_docx_code_typo_in_cover_blocks_publication(extract) -> None:  # type: ignore[no-untyped-def]
    result = extract("LC-SGC-500")

    assert result.status is ExtractionStatus.SOURCE_CODE_UNRESOLVED
    [conflict] = [i for i in result.issues if i.type == "source_code_conflict"]
    assert conflict.details["content"]["cover"] == "LC-SGCC-500"
