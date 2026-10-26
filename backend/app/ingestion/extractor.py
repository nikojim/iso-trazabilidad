"""Extracción pura de referencias: ``ruta -> ExtractionResult`` (sin base de datos)."""

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from app.ingestion.codes import find_candidates, find_codes, split_code
from app.ingestion.config import ExtractionConfig
from app.ingestion.identify import identify_source
from app.ingestion.normalize import heading_key
from app.ingestion.ocr_detect import requires_ocr, scanned_pages
from app.ingestion.readers import EncryptedDocumentError, ReadError, detect_format, read_document
from app.ingestion.sections import SectionOutcome, SectionState, check_bookmarks, find_section
from app.ingestion.types import (
    BlockKind,
    DocumentContent,
    ExtractionResult,
    Issue,
    Occurrence,
    ReferenceHit,
    TextBlock,
)
from app.models.enums import ExtractionStatus, FileFormat, Severity

EVIDENCE_MAX_CHARS = 300


def extract_document(
    path: Path,
    *,
    code_override: str | None = None,
    config: ExtractionConfig | None = None,
) -> ExtractionResult:
    config = config or ExtractionConfig()
    result = ExtractionResult(
        file_path=str(path),
        file_format=detect_format(path),
        source_code=None,
        code_source=None,
        version=None,
        title=None,
        status=ExtractionStatus.ERROR,
    )
    try:
        content = read_document(path)
    except EncryptedDocumentError as exc:
        result.issues.append(Issue("encrypted", Severity.ERROR, str(exc)))
        return result
    except ReadError as exc:
        result.issues.append(Issue("read_error", Severity.ERROR, str(exc)))
        return result

    _apply_identity(result, path, content, code_override)
    if content.file_format is FileFormat.XLSX:
        # Las planillas se pueden citar, pero no tienen sección REFERENCIAS que analizar.
        result.status = (
            ExtractionStatus.NOT_APPLICABLE
            if result.source_code
            else ExtractionStatus.SOURCE_CODE_UNRESOLVED
        )
        return result
    if content.file_format is FileFormat.PDF and requires_ocr(content.pages):
        result.ocr_pages = scanned_pages(content.pages)
        result.status = ExtractionStatus.REQUIRES_OCR
        result.issues.append(
            Issue(
                "requires_ocr",
                Severity.WARNING,
                "El PDF no tiene texto utilizable; requiere OCR",
                {"scanned_pages": result.ocr_pages, "page_count": content.page_count},
            )
        )
        return result

    outcome = find_section(content.blocks, config)
    if content.file_format is FileFormat.PDF:
        check_bookmarks(outcome, content.bookmarks, content.blocks, config)
    _warn_textboxes(result, content, config)
    result.section = outcome.span
    result.issues.extend(outcome.issues)
    references, reference_issues = collect_references(outcome.entries, result.source_code)
    result.references = references
    result.issues.extend(reference_issues)
    result.status = _status(result, outcome, content)
    return result


def _apply_identity(
    result: ExtractionResult, path: Path, content: DocumentContent, code_override: str | None
) -> None:
    identity = identify_source(path, content, code_override)
    result.source_code = identity.code
    result.code_source = identity.code_source
    result.version = identity.version
    result.title = identity.title
    result.page_count = content.page_count
    result.issues.extend(identity.issues)
    result.metadata = {**content.metadata}
    if identity.document_kind:
        result.metadata["document_kind"] = identity.document_kind


def _warn_textboxes(
    result: ExtractionResult, content: DocumentContent, config: ExtractionConfig
) -> None:
    for text in content.textbox_texts:
        if any(alias in heading_key(text) for alias in config.section_aliases):
            result.issues.append(
                Issue(
                    "textbox_content",
                    Severity.WARNING,
                    "Un cuadro de texto menciona REFERENCIAS; su contenido no se analiza",
                    {"text": text[:EVIDENCE_MAX_CHARS]},
                )
            )


def _status(
    result: ExtractionResult, outcome: SectionOutcome, content: DocumentContent
) -> ExtractionStatus:
    if outcome.state is SectionState.NOT_FOUND and scanned_pages(content.pages):
        # La sección podría estar en una página escaneada: no se puede afirmar que no existe.
        result.ocr_pages = scanned_pages(content.pages)
        result.issues.append(
            Issue(
                "requires_ocr",
                Severity.WARNING,
                "No se encontró REFERENCIAS y hay páginas escaneadas",
                {"scanned_pages": result.ocr_pages},
            )
        )
        return ExtractionStatus.REQUIRES_OCR
    if result.source_code is None:
        return ExtractionStatus.SOURCE_CODE_UNRESOLVED
    if outcome.state in (SectionState.AMBIGUOUS, SectionState.UNCERTAIN):
        return ExtractionStatus.NEEDS_REVIEW
    if outcome.state is SectionState.NOT_FOUND:
        return ExtractionStatus.NO_SECTION
    return ExtractionStatus.OK if result.references else ExtractionStatus.NO_REFERENCES


@dataclass(slots=True)
class _Accumulator:
    occurrences: list[Occurrence] = field(default_factory=list)
    title_hint: str | None = None


def collect_references(
    entries: list[tuple[TextBlock, str]], source_code: str | None
) -> tuple[list[ReferenceHit], list[Issue]]:
    """Agrupa las ocurrencias en relaciones lógicas únicas por código destino."""
    by_code: dict[str, _Accumulator] = {}
    issues: list[Issue] = []
    ordinal = 0
    reading_order_warned = False

    for position, (block, group) in enumerate(entries):
        matches = find_codes(block.text, allow_leading_unbracketed=True)
        if len(matches) > 1 and block.kind is BlockKind.LINE and not reading_order_warned:
            reading_order_warned = True
            issues.append(
                Issue(
                    "reading_order_ambiguous",
                    Severity.WARNING,
                    "Una línea de REFERENCIAS contiene varios códigos (¿columnas o tabla?)",
                    {"page": block.page, "text": block.text[:EVIDENCE_MAX_CHARS]},
                )
            )
        for match in matches:
            if not match.bracketed:
                issues.append(
                    Issue(
                        "unbracketed_reference",
                        Severity.INFO,
                        f"{match.code} se tomó como referencia aunque no tiene corchetes",
                        {
                            "code": match.code,
                            "page": block.page,
                            "text": block.text[:EVIDENCE_MAX_CHARS],
                        },
                    )
                )
            ordinal += 1
            accumulator = by_code.setdefault(match.code, _Accumulator())
            accumulator.title_hint = (
                accumulator.title_hint or match.title_hint or _title_from_row(entries, position)
            )
            accumulator.occurrences.append(
                Occurrence(
                    group=group,
                    ordinal=ordinal,
                    raw_text=match.raw,
                    evidence_excerpt=block.text[:EVIDENCE_MAX_CHARS],
                    page_number=block.page,
                    paragraph_index=block.paragraph_index,
                    table_index=block.table_index,
                    row_index=block.row_index,
                    cell_index=block.cell_index,
                )
            )
        issues.extend(_candidate_issues(block))

    references = []
    for code, accumulator in by_code.items():
        occurrences = accumulator.occurrences
        if code == source_code:
            issues.append(
                Issue(
                    "self_reference",
                    Severity.WARNING,
                    f"El documento se referencia a sí mismo ({code}); no se crea la relación",
                    {"code": code, "pages": [o.page_number for o in occurrences]},
                )
            )
            continue
        groups = Counter(o.group for o in occurrences)
        first_seen = {o.group: o.ordinal for o in reversed(occurrences)}
        predominant = max(groups, key=lambda g: (groups[g], -first_seen[g]))
        if len(occurrences) > 1:
            issues.append(
                Issue(
                    "duplicate_in_section",
                    Severity.INFO,
                    f"{code} aparece {len(occurrences)} veces en REFERENCIAS",
                    {"code": code, "count": len(occurrences)},
                )
            )
        if len(groups) > 1:
            issues.append(
                Issue(
                    "mixed_groups",
                    Severity.INFO,
                    f"{code} aparece en más de un grupo: {sorted(groups)}",
                    {"code": code, "groups": dict(groups), "predominant": predominant},
                )
            )
        document_type, system_code = split_code(code)
        references.append(
            ReferenceHit(
                code=code,
                document_type=document_type,
                system_code=system_code,
                group=predominant,
                has_mixed_groups=len(groups) > 1,
                title_hint=accumulator.title_hint,
                occurrences=occurrences,
            )
        )
    return references, issues


def _title_from_row(entries: list[tuple[TextBlock, str]], position: int) -> str | None:
    """En una tabla "código | título", el título está en la celda siguiente de la misma fila."""
    block = entries[position][0]
    if block.table_index is None or position + 1 >= len(entries):
        return None
    following = entries[position + 1][0]
    same_row = (following.table_index, following.row_index) == (block.table_index, block.row_index)
    if same_row and not find_codes(following.text, allow_leading_unbracketed=True):
        return following.text
    return None


def _candidate_issues(block: TextBlock) -> list[Issue]:
    issues = []
    for candidate in find_candidates(block.text, allow_leading_unbracketed=True):
        if candidate.well_formed:
            issues.append(
                Issue(
                    "unbracketed_code",
                    Severity.WARNING,
                    f"Código sin corchetes en REFERENCIAS: {candidate.raw}; no se toma "
                    "como relación",
                    {"raw": candidate.raw, "page": block.page},
                )
            )
        else:
            issues.append(
                Issue(
                    "invalid_reference_candidate",
                    Severity.WARNING,
                    f"Texto con forma de código no válido: {candidate.raw}",
                    {"raw": candidate.raw, "page": block.page},
                )
            )
    return issues
