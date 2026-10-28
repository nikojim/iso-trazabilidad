"""Extracción de punta a punta sobre documentos sintéticos (casos obligatorios del SKILL)."""

from collections import Counter
from pathlib import Path

import pytest

from app.ingestion.extractor import extract_document
from app.ingestion.types import ExtractionResult
from app.models.enums import CodeSource, ExtractionStatus
from tests.fixtures.builders import (
    ACCEPTANCE_GENERAL,
    ACCEPTANCE_PROCEDURES,
    MANUAL_HEADER,
    Heading,
    Line,
    Para,
    TableBlock,
    TextBox,
    build_docx,
    build_pdf,
    build_xlsx,
    heading,
    manual_docx_items,
    manual_pages,
    ref,
)

MANUAL_NAME = "MC-SGG-435-23 Manual de los Sistemas de Gestión"
OUTSIDE_CODES = {"AC-AFP-698"}  # solo aparece fuera de REFERENCIAS en los fixtures


def assert_acceptance_case(result: ExtractionResult) -> None:
    codes = [ref.code for ref in result.references]
    groups = Counter(ref.group for ref in result.references)
    by_code = {ref.code: ref for ref in result.references}

    assert result.status is ExtractionStatus.OK
    assert result.source_code == "MC-SGG-435"
    assert result.occurrence_count == 36
    assert len(codes) == len(set(codes)) == 35
    assert groups == {"general": 27, "procedimientos": 8}
    assert len(by_code["PR-SGG-101"].occurrences) == 2
    assert set(codes) == set(ACCEPTANCE_GENERAL) | set(ACCEPTANCE_PROCEDURES)


def test_acceptance_case_pdf(tmp_path: Path) -> None:
    result = extract_document(
        build_pdf(tmp_path / f"{MANUAL_NAME}.pdf", manual_pages(), header=MANUAL_HEADER)
    )

    assert_acceptance_case(result)
    assert result.code_source is CodeSource.FILENAME_AND_CONTENT
    assert (result.section.start_page, result.section.end_page) == (3, 4)
    assert result.section.terminator == "historial"


def test_acceptance_case_pdf_page_numbers_per_occurrence(tmp_path: Path) -> None:
    result = extract_document(
        build_pdf(tmp_path / f"{MANUAL_NAME}.pdf", manual_pages(), header=MANUAL_HEADER)
    )
    pages = {ref.code: ref.occurrences[0].page_number for ref in result.references}

    assert pages["PO-SGS-400"] == 3
    assert pages["ES-SGG-547"] == 4  # después del salto de página
    assert pages["PR-SGS-402"] == 4


def test_acceptance_case_docx_paragraphs(tmp_path: Path) -> None:
    result = extract_document(
        build_docx(
            tmp_path / f"{MANUAL_NAME}.docx", manual_docx_items(), localized_heading_ids=True
        )
    )

    assert_acceptance_case(result)


def test_acceptance_case_docx_table(tmp_path: Path) -> None:
    result = extract_document(
        build_docx(tmp_path / f"{MANUAL_NAME}.docx", manual_docx_items(references_in_table=True))
    )

    assert_acceptance_case(result)
    evidence = result.references[0].occurrences[0]
    assert (evidence.table_index, evidence.row_index, evidence.cell_index) == (1, 0, 0)


def test_codes_outside_the_section_are_ignored(tmp_path: Path) -> None:
    result = extract_document(
        build_pdf(tmp_path / f"{MANUAL_NAME}.pdf", manual_pages(), header=MANUAL_HEADER)
    )

    assert OUTSIDE_CODES.isdisjoint(ref.code for ref in result.references)
    # ES-SGG-547 sí está en REFERENCIAS: la mención de §3 no suma ocurrencias.
    assert len(next(r for r in result.references if r.code == "ES-SGG-547").occurrences) == 1


def test_document_without_section_is_registered_silently(tmp_path: Path) -> None:
    pdf = build_pdf(
        tmp_path / "LC-SGSA-915-02 Tabla de Documentos del SGSA.pdf",
        [[heading("1 HISTORIAL"), heading("2 LISTADO"), Line("AL-SGSA-911 Alcance")]],
    )

    result = extract_document(pdf)

    assert result.status is ExtractionStatus.NO_SECTION
    assert result.references == []
    assert result.issues == []


def test_empty_section_means_no_references(tmp_path: Path) -> None:
    pdf = build_pdf(
        tmp_path / "PO-SGS-400-01 Política.pdf",
        [[heading("4 REFERENCIAS"), Line("No aplica"), heading("5 HISTORIAL")]],
    )

    assert extract_document(pdf).status is ExtractionStatus.NO_REFERENCES


def test_uncertain_end_needs_review(tmp_path: Path) -> None:
    pdf = build_pdf(
        tmp_path / "PO-SGS-400-01 Política.pdf",
        [[heading("4 REFERENCIAS"), ref("ES-SGC-001"), Line("Texto que sigue sin encabezado")]],
    )

    result = extract_document(pdf)

    assert result.status is ExtractionStatus.NEEDS_REVIEW
    assert "section_end_uncertain" in {i.type for i in result.issues}


def test_scanned_pdf_requires_ocr(tmp_path: Path) -> None:
    pdf = build_pdf(tmp_path / "PO-SGS-400-01 Política.pdf", [[], []], scanned_pages={1, 2})

    result = extract_document(pdf)

    assert result.status is ExtractionStatus.REQUIRES_OCR
    assert result.ocr_pages == [1, 2]
    assert result.references == []


def test_missing_section_with_scanned_pages_requires_ocr(tmp_path: Path) -> None:
    text_page = [heading("1 OBJETIVO"), Line("Texto " * 20)]
    pdf = build_pdf(
        tmp_path / "PO-SGS-400-01 Política.pdf",
        [text_page, [], text_page, text_page, text_page],
        scanned_pages={2},
    )

    result = extract_document(pdf)

    assert result.status is ExtractionStatus.REQUIRES_OCR
    assert result.ocr_pages == [2]


def test_blank_page_does_not_trigger_ocr(tmp_path: Path) -> None:
    pdf = build_pdf(
        tmp_path / "PC-SGSA-936-01 Plan.pdf",
        [
            [heading("1 OBJETIVO")],
            [],
            [heading("4 REFERENCIAS"), ref("ES-SGG-597"), heading("5 HISTORIAL")],
        ],
    )

    result = extract_document(pdf)

    assert result.status is ExtractionStatus.OK
    assert result.ocr_pages == []


def test_encrypted_and_corrupt_files_are_errors(tmp_path: Path) -> None:
    encrypted = build_pdf(tmp_path / "PO-SGS-400-01 A.pdf", [[Line("x")]], encrypt=True)
    corrupt = tmp_path / "PO-SGS-401-01 B.pdf"
    corrupt.write_bytes(b"basura")

    assert [i.type for i in extract_document(encrypted).issues] == ["encrypted"]
    assert [i.type for i in extract_document(corrupt).issues] == ["read_error"]
    assert extract_document(corrupt).status is ExtractionStatus.ERROR


def test_self_reference_reported_without_edge(tmp_path: Path) -> None:
    pdf = build_pdf(
        tmp_path / "PO-SGS-400-01 Política.pdf",
        [[heading("4 REFERENCIAS"), ref("PO-SGS-400"), ref("ES-SGC-001"), heading("5 HISTORIAL")]],
    )

    result = extract_document(pdf)

    assert [r.code for r in result.references] == ["ES-SGC-001"]
    assert "self_reference" in {i.type for i in result.issues}


def test_mixed_groups_keep_predominant_group(tmp_path: Path) -> None:
    pdf = build_pdf(
        tmp_path / "PO-SGS-400-01 Política.pdf",
        [
            [
                heading("4 REFERENCIAS"),
                ref("PR-SGG-101"),
                Line("Procedimientos", bold=True),
                ref("PR-SGG-101"),
                ref("PR-SGG-101"),
                heading("5 HISTORIAL"),
            ]
        ],
    )

    [reference] = extract_document(pdf).references

    assert reference.group == "procedimientos"
    assert reference.has_mixed_groups


def test_pr_codes_without_subsection_stay_general(tmp_path: Path) -> None:
    pdf = build_pdf(
        tmp_path / "PC-SGSA-914-02 Plan.pdf",
        [[heading("4 REFERENCIAS"), ref("PR-SGG-000"), ref("PO-SGS-400"), heading("5 HISTORIAL")]],
    )

    assert {r.group for r in extract_document(pdf).references} == {"general"}


def test_invalid_and_unbracketed_codes_inside_section_are_reported(tmp_path: Path) -> None:
    pdf = build_pdf(
        tmp_path / "PO-SGS-400-01 Política.pdf",
        [
            [
                heading("4 REFERENCIAS"),
                Line("[ES-SG-1] Mal escrito"),
                Line("Ver también ES-SGC-002 en prosa"),
                ref("AL-SGS-401"),
                heading("5 HISTORIAL"),
            ]
        ],
    )

    result = extract_document(pdf)
    types = Counter(i.type for i in result.issues)

    assert [r.code for r in result.references] == ["AL-SGS-401"]
    assert types["invalid_reference_candidate"] == 1
    assert types["unbracketed_code"] == 1


def test_leading_unbracketed_code_inside_section_is_accepted(tmp_path: Path) -> None:
    pdf = build_pdf(
        tmp_path / "PO-SGS-400-01 Política.pdf",
        [
            [
                heading("3 RESPONSABILIDADES"),
                Line("ES-SGC-100 Perfiles de Cargo"),  # mismo formato, pero fuera de la sección
                heading("4 REFERENCIAS"),
                Line("ES-SGC-001 Política de la Calidad"),
                ref("AL-SGS-401"),
                heading("5 HISTORIAL"),
            ]
        ],
    )

    result = extract_document(pdf)

    assert [(r.code, r.title_hint) for r in result.references] == [
        ("ES-SGC-001", "Política de la Calidad"),
        ("AL-SGS-401", "Documento referenciado"),
    ]
    assert result.references[0].occurrences[0].raw_text == "ES-SGC-001"
    assert [i.type for i in result.issues] == ["unbracketed_reference"]


def test_docx_reference_table_with_code_alone_in_a_cell(tmp_path: Path) -> None:
    path = build_docx(
        tmp_path / "IN-SGG-001-02 Manual CRM.docx",
        [
            Heading("REFERENCIAS"),
            TableBlock([["ES-SGG-003", "Especificaciones de implementación CRM"]]),
            Heading("HISTORIAL"),
            TableBlock([["01", "Se agrega ES-SGG-004"]]),
        ],
    )

    result = extract_document(path)

    assert result.status is ExtractionStatus.OK
    [reference] = result.references
    assert (reference.code, reference.title_hint) == (
        "ES-SGG-003",
        "Especificaciones de implementación CRM",
    )
    assert (reference.occurrences[0].table_index, reference.occurrences[0].cell_index) == (0, 0)


def test_two_codes_on_one_pdf_line_warn_about_reading_order(tmp_path: Path) -> None:
    pdf = build_pdf(
        tmp_path / "PO-SGS-400-01 Política.pdf",
        [
            [
                heading("4 REFERENCIAS"),
                Line("[ES-SGC-001]", right="[AL-SGS-401]"),
                heading("5 HISTORIAL"),
            ]
        ],
    )

    result = extract_document(pdf)

    assert len(result.references) == 2
    assert "reading_order_ambiguous" in {i.type for i in result.issues}


def test_bookmark_mismatch_is_reported(tmp_path: Path) -> None:
    pdf = build_pdf(
        tmp_path / "PO-SGS-400-01 Política.pdf",
        [[heading("4 REFERENCIAS"), ref("ES-SGC-001")], [heading("5 HISTORIAL")]],
        bookmarks=[[1, "4 REFERENCIAS", 2], [1, "5 HISTORIAL", 2]],
    )

    result = extract_document(pdf)

    assert result.status is ExtractionStatus.OK
    assert "bookmark_mismatch" in {i.type for i in result.issues}


def test_source_code_conflict_blocks_publication(tmp_path: Path) -> None:
    pdf = build_pdf(
        tmp_path / "PO-SGS-400-01 Política.pdf",
        [
            [
                Line("Referencia/Versión : PO-SGS-999/01"),
                heading("4 REFERENCIAS"),
                ref("ES-SGC-001"),
                heading("5 HISTORIAL"),
            ]
        ],
    )

    result = extract_document(pdf)

    assert result.status is ExtractionStatus.SOURCE_CODE_UNRESOLVED
    assert result.source_code is None
    assert [r.code for r in result.references] == ["ES-SGC-001"]  # visibles para diagnóstico


def test_code_override(tmp_path: Path) -> None:
    pdf = build_pdf(
        tmp_path / "documento.pdf",
        [[heading("4 REFERENCIAS"), ref("ES-SGC-001"), heading("5 HISTORIAL")]],
    )

    result = extract_document(pdf, code_override="PO-SGS-400")

    assert (result.source_code, result.code_source) == ("PO-SGS-400", CodeSource.OVERRIDE)
    assert result.status is ExtractionStatus.OK


def test_docx_textbox_mentioning_references_is_warned(tmp_path: Path) -> None:
    path = build_docx(
        tmp_path / "PO-SGS-400-01 Política.docx",
        [TextBox("REFERENCIAS [ES-SGC-001]"), Heading("HISTORIAL"), Para("texto")],
    )

    result = extract_document(path)

    assert result.status is ExtractionStatus.NO_SECTION
    assert [i.type for i in result.issues] == ["textbox_content"]


@pytest.mark.parametrize("text", ["[ es-sgc-001 ] Política", "[ES‑SGC–001] Política"])
def test_docx_variants_of_case_spaces_and_unicode_dashes(tmp_path: Path, text: str) -> None:
    path = build_docx(
        tmp_path / "PO-SGS-400-01 Política.docx",
        [Heading("Referencias"), Para(text), Heading("Historial")],
    )

    assert [r.code for r in extract_document(path).references] == ["ES-SGC-001"]


def test_spreadsheet_is_identified_but_not_analyzed(tmp_path: Path) -> None:
    sheet = build_xlsx(tmp_path / "RG-SGSA-927-02 Inventario.xlsx")

    result = extract_document(sheet)

    assert result.status is ExtractionStatus.NOT_APPLICABLE
    assert (result.source_code, result.code_source) == ("RG-SGSA-927", CodeSource.FILENAME)
    assert (result.version, result.title) == ("02", "Inventario")
    assert result.references == [] and result.issues == []  # el [PO-SGS-400] de la celda no cuenta


def test_legacy_xls_is_identified_by_filename(tmp_path: Path) -> None:
    sheet = tmp_path / "RG-SGSA-931-03 Planilla antigua.xls"
    sheet.write_bytes(bytes.fromhex("D0CF11E0A1B11AE1") + b"\0" * 512)

    result = extract_document(sheet)

    assert result.status is ExtractionStatus.NOT_APPLICABLE
    assert (result.source_code, result.version) == ("RG-SGSA-931", "03")


def test_spreadsheet_without_code_is_unresolved(tmp_path: Path) -> None:
    result = extract_document(build_xlsx(tmp_path / "inventario.xlsx"))

    assert result.status is ExtractionStatus.SOURCE_CODE_UNRESOLVED
    assert [issue.type for issue in result.issues] == ["source_code_missing"]
