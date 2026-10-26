"""Estructuras de datos del pipeline de extracción (sin dependencias de base de datos)."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.models.enums import CodeSource, ExtractionStatus, FileFormat, Severity


class BlockKind(StrEnum):
    LINE = "line"  # línea visual de un PDF
    PARAGRAPH = "paragraph"  # párrafo de DOCX fuera de tablas
    CELL = "cell"  # párrafo dentro de una celda de tabla DOCX
    TEXTBOX = "textbox"  # cuadro de texto DOCX (no participa de la sección)


@dataclass(frozen=True, slots=True)
class TextBlock:
    text: str  # normalizado
    raw_text: str
    kind: BlockKind
    page: int | None = None
    paragraph_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    cell_index: int | None = None
    style: str | None = None
    heading_level: int | None = None  # nivel declarado por estilo/outline (DOCX)
    is_toc: bool = False  # estilo de tabla de contenido (DOCX)
    is_bold: bool = False
    font_size: float | None = None
    bbox: tuple[float, float, float, float] | None = None
    is_furniture: bool = False  # encabezado/pie de página repetido (PDF)


@dataclass(frozen=True, slots=True)
class Bookmark:
    level: int
    title: str
    page: int


@dataclass(frozen=True, slots=True)
class PageStats:
    number: int
    char_count: int
    image_coverage: float


@dataclass(slots=True)
class DocumentContent:
    file_format: FileFormat
    blocks: list[TextBlock]
    page_count: int | None = None
    pages: list[PageStats] = field(default_factory=list)
    bookmarks: list[Bookmark] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    # Encabezados de página de Word (fuera del cuerpo); sirven para identificar el documento.
    header_texts: list[str] = field(default_factory=list)
    # Cuadros de texto de Word: no participan de la sección REFERENCIAS.
    textbox_texts: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Issue:
    type: str
    severity: Severity
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Occurrence:
    group: str
    ordinal: int
    raw_text: str
    evidence_excerpt: str
    page_number: int | None = None
    paragraph_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    cell_index: int | None = None


@dataclass(slots=True)
class ReferenceHit:
    """Relación lógica única hacia ``code`` con todas sus ocurrencias."""

    code: str
    document_type: str
    system_code: str
    group: str
    has_mixed_groups: bool
    title_hint: str | None
    occurrences: list[Occurrence]


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    code: str | None
    version: str | None
    title: str | None
    code_source: CodeSource | None
    document_kind: str | None = None  # "Tipo de documento" de la portada (Manual, Política…)
    issues: tuple[Issue, ...] = ()


@dataclass(frozen=True, slots=True)
class SectionSpan:
    start_page: int | None
    end_page: int | None
    start_block: int
    end_block: int  # exclusivo
    terminator: str | None  # clave del encabezado que cerró la sección


@dataclass(slots=True)
class ExtractionResult:
    file_path: str
    file_format: FileFormat | None
    source_code: str | None
    code_source: CodeSource | None
    version: str | None
    title: str | None
    status: ExtractionStatus
    references: list[ReferenceHit] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    section: SectionSpan | None = None
    page_count: int | None = None
    ocr_pages: list[int] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def occurrence_count(self) -> int:
        return sum(len(ref.occurrences) for ref in self.references)
