"""Delimitación de REFERENCIAS sobre bloques construidos a mano (independiente del formato)."""

from app.ingestion.config import ExtractionConfig
from app.ingestion.normalize import normalize_text
from app.ingestion.sections import (
    SectionState,
    check_bookmarks,
    classify_heading,
    find_section,
)
from app.ingestion.types import BlockKind, Bookmark, TextBlock

CONFIG = ExtractionConfig()


def line(text: str, page: int = 1, *, bold: bool = False, size: float = 10.0) -> TextBlock:
    return TextBlock(
        text=normalize_text(text),
        raw_text=text,
        kind=BlockKind.LINE,
        page=page,
        is_bold=bold,
        font_size=size,
    )


def h(text: str, page: int = 1) -> TextBlock:
    return line(text, page, bold=True, size=13.0)


def codes_in(outcome) -> list[str]:  # type: ignore[no-untyped-def]
    return [block.text for block, _ in outcome.entries]


def test_numbered_section_ends_at_next_same_level_heading() -> None:
    blocks = [
        h("3 RESPONSABILIDADES"),
        line("SGSI [ES-SGG-547] Perfiles"),
        h("4 REFERENCIAS"),
        line("[PO-SGS-400] Política"),
        h("4.1 Normas externas"),  # subnivel desconocido: no cierra
        line("[ES-SGC-001] Política de la Calidad"),
        h("5 HISTORIAL"),
        line("[ES-SGG-597] fuera de la sección"),
    ]

    outcome = find_section(blocks, CONFIG)

    assert outcome.state is SectionState.FOUND
    assert codes_in(outcome) == ["[PO-SGS-400] Política", "[ES-SGC-001] Política de la Calidad"]
    assert outcome.span.terminator == "historial"
    assert [i.type for i in outcome.issues] == ["unknown_subheading"]


def test_subgroup_changes_group_without_closing() -> None:
    blocks = [
        h("4 REFERENCIAS"),
        line("[PO-SGS-400] Política"),
        line("Procedimientos", bold=True),
        line("[PR-SGG-101] Gestión del Personal"),
        h("5 HISTORIAL"),
    ]

    outcome = find_section(blocks, CONFIG)

    assert [group for _, group in outcome.entries] == ["general", "procedimientos"]


def test_subgroup_recognized_without_heading_format() -> None:
    blocks = [
        h("4 REFERENCIAS"),
        line("[PO-SGS-400] Política"),
        line("Procedimientos"),
        line("[PR-SGG-101] Gestión"),
        h("5 HISTORIAL"),
    ]

    assert [g for _, g in find_section(blocks, CONFIG).entries] == ["general", "procedimientos"]


def test_toc_entry_is_not_the_start_of_the_section() -> None:
    blocks = [
        line("4 REFERENCIAS ............................ 4", bold=True),
        line("5 HISTORIAL .............................. 5", bold=True),
        h("1 OBJETIVO", page=2),
        line("Texto", page=2),
        h("4 REFERENCIAS", page=4),
        line("[PO-SGS-400] Política", page=4),
        h("5 HISTORIAL", page=5),
    ]

    outcome = find_section(blocks, CONFIG)

    assert outcome.span.start_page == 4
    assert codes_in(outcome) == ["[PO-SGS-400] Política"]


def test_only_toc_mention_means_no_section() -> None:
    blocks = [line("4 REFERENCIAS ....... 4", bold=True), h("1 HISTORIAL"), line("texto")]

    assert find_section(blocks, CONFIG).state is SectionState.NOT_FOUND


def test_mention_in_prose_is_not_a_heading() -> None:
    blocks = [
        h("1 OBJETIVO"),
        line("Ver las referencias indicadas en el anexo del documento [ES-SGC-001]."),
        h("2 HISTORIAL"),
    ]

    assert find_section(blocks, CONFIG).state is SectionState.NOT_FOUND


def test_lowercase_accented_heading_detected() -> None:
    blocks = [h("4. Referéncias:"), line("[PO-SGS-400] Política"), h("5. Historial")]

    assert find_section(blocks, CONFIG).state is SectionState.FOUND


def test_page_break_and_furniture_do_not_cut_the_section() -> None:
    footer = TextBlock(
        "MC-SGG-435 / 23 - Manual - Página 4/36",
        "",
        BlockKind.LINE,
        page=5,
        is_furniture=True,
        is_bold=True,
    )
    blocks = [
        h("4 REFERENCIAS", page=4),
        line("[PO-SGS-400] Política", page=4),
        footer,
        line("[ES-SGG-547] Perfiles", page=5),
        h("5 HISTORIAL", page=5),
    ]

    outcome = find_section(blocks, CONFIG)

    assert [b.page for b, _ in outcome.entries] == [4, 5]
    assert (outcome.span.start_page, outcome.span.end_page) == (4, 5)


def test_section_running_to_end_with_trailing_prose_is_uncertain() -> None:
    blocks = [h("4 REFERENCIAS"), line("[PO-SGS-400] Política"), line("Texto libre que sigue")]

    outcome = find_section(blocks, CONFIG)

    assert outcome.state is SectionState.UNCERTAIN
    assert [i.type for i in outcome.issues] == ["section_end_uncertain"]


def test_section_ending_with_document_after_last_code_is_found() -> None:
    blocks = [h("4 REFERENCIAS"), line("[PO-SGS-400] Política")]

    assert find_section(blocks, CONFIG).state is SectionState.FOUND


def test_empty_well_delimited_section_is_found_without_entries() -> None:
    outcome = find_section([h("4 REFERENCIAS"), h("5 HISTORIAL")], CONFIG)

    assert outcome.state is SectionState.FOUND
    assert outcome.entries == []


def test_two_candidates_resolved_by_the_one_with_codes() -> None:
    blocks = [
        h("2 REFERENCIAS"),
        line("Ver más abajo."),
        h("3 ALCANCE"),
        h("4 REFERENCIAS"),
        line("[PO-SGS-400] Política"),
        h("5 HISTORIAL"),
    ]

    outcome = find_section(blocks, CONFIG)

    assert outcome.state is SectionState.FOUND
    assert codes_in(outcome) == ["[PO-SGS-400] Política"]


def test_two_candidates_with_codes_are_ambiguous() -> None:
    blocks = [
        h("2 REFERENCIAS"),
        line("[PO-SGS-400] Política"),
        h("3 ALCANCE"),
        h("4 REFERENCIAS"),
        line("[ES-SGC-001] Calidad"),
        h("5 HISTORIAL"),
    ]

    outcome = find_section(blocks, CONFIG)

    assert outcome.state is SectionState.AMBIGUOUS
    assert outcome.issues[0].type == "section_ambiguous"


def test_unnumbered_section_closed_by_uppercase_heading() -> None:
    blocks = [
        line("REFERENCIAS", bold=True),
        line("[PO-SGS-400] Política"),
        line("Procedimientos", bold=True),
        line("[PR-SGG-101] Gestión"),
        line("CONTROL DE VERSIONES", bold=True),
        line("[ES-SGG-597] fuera"),
    ]

    outcome = find_section(blocks, CONFIG)

    assert codes_in(outcome) == ["[PO-SGS-400] Política", "[PR-SGG-101] Gestión"]


def test_docx_style_level_closes_at_same_level() -> None:
    def styled(text: str, level: int | None) -> TextBlock:
        return TextBlock(text, text, BlockKind.PARAGRAPH, heading_level=level)

    blocks = [
        styled("REFERENCIAS", 1),
        styled("[PO-SGS-400] Política", None),
        styled("Procedimientos", 2),
        styled("[PR-SGG-101] Gestión", None),
        styled("HISTORIAL", 1),
        styled("[ES-SGG-597] fuera", None),
    ]

    outcome = find_section(blocks, CONFIG)

    assert [(b.text, g) for b, g in outcome.entries] == [
        ("[PO-SGS-400] Política", "general"),
        ("[PR-SGG-101] Gestión", "procedimientos"),
    ]


def test_numbered_list_items_in_body_are_not_headings() -> None:
    assert classify_heading(line("1. Provisión del Software Aplicativo para la AFAP"), 10.0) is None
    assert classify_heading(line("01 10/03/2026 Final Creación del documento"), 10.0) is None


def test_short_line_is_not_a_heading_because_of_font_size_alone() -> None:
    # En documentos cortos el pie de página (8 pt) puede pesar más que el cuerpo (10 pt).
    assert classify_heading(line("Nota aclaratoria final", size=10.0), 8.0) is None


def test_line_with_code_is_never_a_heading() -> None:
    assert classify_heading(line("ES-SGC-001 SIN CORCHETES", bold=True), 10.0) is None


def test_numbered_bold_heading_levels() -> None:
    assert classify_heading(h("4 REFERENCIAS"), 10.0).level == 1
    assert classify_heading(line("7.2.1 Productos", bold=True), 10.0).level == 3


class TestBookmarks:
    blocks = [
        h("4 REFERENCIAS", page=4),
        line("[PO-SGS-400] Política", page=4),
        h("5 HISTORIAL", page=5),
    ]

    def test_matching_bookmarks_add_no_issue(self) -> None:
        outcome = find_section(self.blocks, CONFIG)
        check_bookmarks(
            outcome,
            [Bookmark(1, "4 REFERENCIAS", 4), Bookmark(1, "5 HISTORIAL", 5)],
            self.blocks,
            CONFIG,
        )
        assert outcome.issues == []

    def test_mismatching_bookmarks_warn(self) -> None:
        outcome = find_section(self.blocks, CONFIG)
        check_bookmarks(
            outcome,
            [Bookmark(1, "4 REFERENCIAS", 3), Bookmark(1, "5 HISTORIAL", 5)],
            self.blocks,
            CONFIG,
        )
        assert [i.type for i in outcome.issues] == ["bookmark_mismatch"]
        assert outcome.state is SectionState.FOUND

    def test_bookmark_confirms_section_running_to_end(self) -> None:
        blocks = [
            h("4 REFERENCIAS", page=4),
            line("[PO-SGS-400] Política", page=4),
            line("Nota final"),
        ]
        outcome = find_section(blocks, CONFIG)
        assert outcome.state is SectionState.UNCERTAIN

        check_bookmarks(outcome, [Bookmark(1, "4 REFERENCIAS", 4)], blocks, CONFIG)

        assert outcome.state is SectionState.FOUND
        assert outcome.issues == []

    def test_bookmark_without_detected_heading_needs_review(self) -> None:
        blocks = [line("texto sin encabezados"), line("[PO-SGS-400] Política")]
        outcome = find_section(blocks, CONFIG)

        check_bookmarks(outcome, [Bookmark(1, "Referencias", 1)], blocks, CONFIG)

        assert outcome.state is SectionState.AMBIGUOUS
        assert [i.type for i in outcome.issues] == ["bookmark_mismatch"]
