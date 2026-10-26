"""Delimitación de la sección REFERENCIAS y de sus subgrupos.

Inicio: encabezado (fuera de la tabla de contenido) cuya clave es un alias de REFERENCIAS.
Fin: siguiente encabezado de nivel igual o superior, o un terminador configurado.
Los subgrupos (p. ej. "Procedimientos") cambian el grupo sin cerrar la sección.
Ante cualquier duda el resultado es ambiguo o incierto: nunca se asume "sin referencias".
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum

from app.ingestion.codes import REFERENCE_PATTERN
from app.ingestion.config import DEFAULT_GROUP, ExtractionConfig
from app.ingestion.normalize import heading_key
from app.ingestion.types import BlockKind, Bookmark, Issue, SectionSpan, TextBlock
from app.models.enums import Severity

_NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(\S.{1,79})$")
_TOC_ENTRY = re.compile(r"(?:\.{3,}|…{2,}|(?:\.\s){3,})\s*\d+\s*$")
_TOC_TAB_PAGE = re.compile(r"\t\s*\d+\s*$")
_LETTERS = re.compile(r"[^\W\d_]")
_CODE_LIKE = re.compile(r"\b[A-Z]{1,5}-[A-Z0-9]{1,6}-\d{1,6}\b")
MAX_UNNUMBERED_HEADING_WORDS = 6
MAX_UNNUMBERED_HEADING_CHARS = 60
LARGER_FONT_FACTOR = 1.15


class SectionState(StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    UNCERTAIN = "uncertain"  # se llegó al final del documento sin un cierre claro


@dataclass(frozen=True, slots=True)
class Heading:
    key: str
    level: int | None  # None: encabezado sin numeración ni nivel declarado
    numbered: bool


@dataclass(slots=True)
class SectionOutcome:
    state: SectionState
    span: SectionSpan | None = None
    entries: list[tuple[TextBlock, str]] = field(default_factory=list)  # (bloque, grupo)
    issues: list[Issue] = field(default_factory=list)


def is_toc_entry(block: TextBlock) -> bool:
    return (
        block.is_toc
        or bool(_TOC_ENTRY.search(block.text))
        or bool(_TOC_TAB_PAGE.search(block.raw_text))
    )


def _mostly_upper(text: str) -> bool:
    letters = _LETTERS.findall(text)
    return len(letters) >= 3 and sum(ch.isupper() for ch in letters) >= 0.8 * len(letters)


def body_font_size(blocks: list[TextBlock]) -> float | None:
    """Tamaño de fuente predominante del cuerpo, ponderado por cantidad de caracteres."""
    sizes: Counter[float] = Counter()
    for block in blocks:
        if block.font_size is not None and not block.is_furniture:
            sizes[round(block.font_size, 1)] += len(block.text)
    return sizes.most_common(1)[0][0] if sizes else None


def classify_heading(block: TextBlock, body_size: float | None) -> Heading | None:
    if block.kind is BlockKind.TEXTBOX or block.is_furniture or is_toc_entry(block):
        return None
    text = block.text
    if not text or "[" in text or _CODE_LIKE.search(text):
        return None
    if block.heading_level is not None:
        return Heading(heading_key(text), block.heading_level, numbered=True)

    larger = bool(
        body_size and block.font_size and block.font_size > body_size * LARGER_FONT_FACTOR
    )
    numbered = _NUMBERED.match(text)
    if numbered:
        if block.is_bold or larger or _mostly_upper(numbered.group(2)):
            level = len(numbered.group(1).split("."))
            return Heading(heading_key(text), level, numbered=True)
        return None
    # Sin numeración solo cuentan negrita o MAYÚSCULAS: el tamaño de fuente no es fiable en
    # documentos cortos, donde encabezados y pies de página pesan más que el cuerpo.
    if (
        len(text.split()) <= MAX_UNNUMBERED_HEADING_WORDS
        and len(text) <= MAX_UNNUMBERED_HEADING_CHARS
        and _LETTERS.search(text)
        and (block.is_bold or _mostly_upper(text))
    ):
        return Heading(heading_key(text), None, numbered=False)
    return None


def find_section(blocks: list[TextBlock], config: ExtractionConfig) -> SectionOutcome:
    body_size = body_font_size(blocks)
    headings = {
        index: heading
        for index, block in enumerate(blocks)
        if (heading := classify_heading(block, body_size)) is not None
    }
    candidates = [i for i, h in headings.items() if h.key in config.section_aliases]
    if not candidates:
        return SectionOutcome(SectionState.NOT_FOUND)

    start = _choose_start(candidates, blocks, headings)
    if start is None:
        return SectionOutcome(
            SectionState.AMBIGUOUS,
            issues=[
                Issue(
                    "section_ambiguous",
                    Severity.WARNING,
                    "Hay más de un encabezado REFERENCIAS y no se puede decidir cuál es la sección",
                    {"pages": [blocks[i].page for i in candidates]},
                )
            ],
        )
    return _walk_section(start, blocks, headings, config)


def _choose_start(
    candidates: list[int], blocks: list[TextBlock], headings: dict[int, Heading]
) -> int | None:
    if len(candidates) == 1:
        return candidates[0]
    with_codes = [c for c in candidates if _has_code_before_next_heading(c, blocks, headings)]
    return with_codes[0] if len(with_codes) == 1 else None


def _has_code_before_next_heading(
    start: int, blocks: list[TextBlock], headings: dict[int, Heading]
) -> bool:
    for index in range(start + 1, len(blocks)):
        if index in headings:
            return False
        if REFERENCE_PATTERN.search(blocks[index].text):
            return True
    return False


def _walk_section(
    start: int,
    blocks: list[TextBlock],
    headings: dict[int, Heading],
    config: ExtractionConfig,
) -> SectionOutcome:
    start_heading = headings[start]
    group = DEFAULT_GROUP
    outcome = SectionOutcome(SectionState.FOUND)
    end = len(blocks)
    terminator: str | None = None

    for index in range(start + 1, len(blocks)):
        block = blocks[index]
        if block.is_furniture or block.kind is BlockKind.TEXTBOX or is_toc_entry(block):
            continue
        heading = headings.get(index)
        if heading is None:
            # Un subgrupo conocido cuenta aunque no tenga formato de encabezado (p. ej. una celda).
            key = heading_key(block.text)
            if key in config.subgroups:
                group = config.subgroups[key]
            else:
                outcome.entries.append((block, group))
            continue
        if heading.key in config.subgroups:
            group = config.subgroups[heading.key]
        elif heading.key in config.terminators or _closes(start_heading, heading, block):
            end, terminator = index, heading.key
            break
        else:
            outcome.issues.append(
                Issue(
                    "unknown_subheading",
                    Severity.WARNING,
                    f"Subtítulo no reconocido dentro de REFERENCIAS: {block.text!r}",
                    {"page": block.page, "text": block.text, "group": group},
                )
            )

    if terminator is None and _has_trailing_prose(outcome.entries):
        outcome.state = SectionState.UNCERTAIN
        outcome.issues.append(
            Issue(
                "section_end_uncertain",
                Severity.WARNING,
                "No se encontró el final de REFERENCIAS antes del fin del documento",
                {"start_page": blocks[start].page},
            )
        )
    last_page = outcome.entries[-1][0].page if outcome.entries else blocks[start].page
    outcome.span = SectionSpan(blocks[start].page, last_page, start, end, terminator)
    return outcome


def _closes(start: Heading, heading: Heading, block: TextBlock) -> bool:
    if start.level is not None and heading.level is not None:
        return heading.level <= start.level
    if start.level is None:
        # REFERENCIAS sin numerar: la cierra un encabezado numerado o en MAYÚSCULAS.
        return heading.numbered or _mostly_upper(block.text)
    return False


def _has_trailing_prose(entries: list[tuple[TextBlock, str]]) -> bool:
    """¿Hay texto que no es una línea de referencia después del último código?"""
    last_code = max(
        (i for i, (block, _) in enumerate(entries) if REFERENCE_PATTERN.search(block.text)),
        default=-1,
    )
    return any(_LETTERS.search(block.text) for block, _ in entries[last_code + 1 :])


def check_bookmarks(
    outcome: SectionOutcome,
    bookmarks: list[Bookmark],
    blocks: list[TextBlock],
    config: ExtractionConfig,
) -> None:
    """Contrasta la sección detectada con los marcadores del PDF (señal de confirmación)."""
    position = next(
        (i for i, b in enumerate(bookmarks) if heading_key(b.title) in config.section_aliases),
        None,
    )
    if position is None:
        return
    bookmark = bookmarks[position]
    following = next((b for b in bookmarks[position + 1 :] if b.level <= bookmark.level), None)
    expected = {"start_page": bookmark.page, "end_page": following.page if following else None}

    if outcome.state is SectionState.NOT_FOUND:
        outcome.state = SectionState.AMBIGUOUS
        outcome.issues.append(
            _mismatch("Los marcadores indican REFERENCIAS pero no se detectó", expected)
        )
        return
    if outcome.span is None:
        return
    if outcome.state is SectionState.UNCERTAIN:
        if following is None:
            # El marcador confirma que la sección llega hasta el final del documento.
            outcome.state = SectionState.FOUND
            outcome.issues = [i for i in outcome.issues if i.type != "section_end_uncertain"]
        else:
            outcome.issues.append(
                _mismatch("Los marcadores indican otro final de sección", expected)
            )
        return
    actual_end_page = (
        blocks[outcome.span.end_block].page if outcome.span.end_block < len(blocks) else None
    )
    if outcome.span.start_page != bookmark.page or (
        following is not None and actual_end_page != following.page
    ):
        outcome.issues.append(
            _mismatch(
                "La sección detectada no coincide con los marcadores del PDF",
                {
                    **expected,
                    "detected_start": outcome.span.start_page,
                    "detected_end": actual_end_page,
                },
            )
        )


def _mismatch(message: str, details: dict[str, object]) -> Issue:
    return Issue("bookmark_mismatch", Severity.WARNING, message, details)
