"""Lectura de DOCX con python-docx: párrafos y celdas intercalados en orden documental."""

import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import docx
from docx.document import Document as DocxDocument
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.ns import qn
from docx.styles.style import BaseStyle
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.ingestion.normalize import normalize_text
from app.ingestion.readers import ReadError
from app.ingestion.readers.ooxml import custom_properties
from app.ingestion.types import BlockKind, DocumentContent, TextBlock
from app.models.enums import FileFormat

_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
_BODY_TEXT_OUTLINE_LEVEL = 9


def read_docx(path: Path) -> DocumentContent:
    try:
        document = docx.Document(str(path))
    except (PackageNotFoundError, zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise ReadError(f"No se pudo abrir el DOCX: {exc}") from exc
    walker = _Walker(document)
    walker.walk(document.element.body, document, in_toc=False)
    return DocumentContent(
        file_format=FileFormat.DOCX,
        blocks=walker.blocks,
        metadata=_metadata(document, path),
        header_texts=_header_texts(document),
        textbox_texts=walker.textboxes,
    )


@dataclass
class _Walker:
    document: DocxDocument
    blocks: list[TextBlock] = field(default_factory=list)
    textboxes: list[str] = field(default_factory=list)
    paragraph_counter: int = 0
    table_counter: int = 0

    def walk(
        self,
        element: Any,
        parent: Any,
        in_toc: bool,
        cell: tuple[int, int, int] | None = None,
    ) -> None:
        for child in element.iterchildren():
            if child.tag == qn("w:p"):
                self._paragraph(Paragraph(child, parent), in_toc, cell)
            elif child.tag == qn("w:tbl"):
                self._table(Table(child, parent), in_toc)
            elif child.tag == qn("w:sdt"):
                # Los controles de contenido envuelven, entre otras cosas, la tabla de contenido.
                content = child.find(qn("w:sdtContent"))
                if content is not None:
                    self.walk(content, parent, in_toc or _is_toc_sdt(child), cell)

    def _table(self, table: Table, in_toc: bool) -> None:
        index = self.table_counter
        self.table_counter += 1
        # Se guardan los elementos (no su id(): lxml recicla los proxies y los id se repiten).
        seen: set[Any] = set()
        for row_index, row in enumerate(table.rows):
            for cell_index, table_cell in enumerate(row.cells):
                # Las celdas combinadas se repiten en row.cells: leerlas una sola vez.
                if table_cell._tc in seen:
                    continue
                seen.add(table_cell._tc)
                self.walk(table_cell._tc, table_cell, in_toc, (index, row_index, cell_index))

    def _paragraph(
        self, paragraph: Paragraph, in_toc: bool, cell: tuple[int, int, int] | None
    ) -> None:
        index = self.paragraph_counter
        self.paragraph_counter += 1
        self.textboxes.extend(_textbox_texts(paragraph))
        raw = paragraph.text
        if not raw.strip():
            return
        style = paragraph.style
        style_name = style.name if style is not None else None
        table_index, row_index, cell_index = cell if cell else (None, None, None)
        self.blocks.append(
            TextBlock(
                text=normalize_text(raw),
                raw_text=raw,
                kind=BlockKind.CELL if cell else BlockKind.PARAGRAPH,
                paragraph_index=index,
                table_index=table_index,
                row_index=row_index,
                cell_index=cell_index,
                style=style_name,
                heading_level=_heading_level(paragraph),
                is_toc=in_toc or _is_toc_style(style),
                is_bold=_is_bold(paragraph),
            )
        )


def _style_chain(style: BaseStyle | None) -> Iterator[BaseStyle]:
    while style is not None:
        yield style
        style = style.base_style


def _outline_level(element: Any) -> int | None:
    ppr = element.find(qn("w:pPr")) if element is not None else None
    level = ppr.find(qn("w:outlineLvl")) if ppr is not None else None
    return int(level.get(qn("w:val"))) if level is not None else None


def _heading_level(paragraph: Paragraph) -> int | None:
    """Nivel por nombre interno del estilo ("heading N") u outline; nunca por el ID localizado."""
    own = _outline_level(paragraph._p)
    if own is not None:
        return own + 1 if own < _BODY_TEXT_OUTLINE_LEVEL else None
    for style in _style_chain(paragraph.style):
        name = (style.name or "").casefold()
        if name.startswith("heading ") and name[8:].isdigit():
            return int(name[8:])
        level = _outline_level(style.element)
        if level is not None:
            return level + 1 if level < _BODY_TEXT_OUTLINE_LEVEL else None
    return None


def _is_toc_style(style: BaseStyle | None) -> bool:
    return any((s.name or "").casefold().startswith("toc ") for s in _style_chain(style))


def _is_toc_sdt(sdt: Any) -> bool:
    gallery = sdt.find(f"{qn('w:sdtPr')}/{qn('w:docPartObj')}/{qn('w:docPartGallery')}")
    return gallery is not None and "contents" in (gallery.get(qn("w:val")) or "").casefold()


def _is_bold(paragraph: Paragraph) -> bool:
    runs = [run for run in paragraph.runs if run.text.strip()]
    if not runs:
        return False
    style_bold = any(s.font.bold for s in _style_chain(paragraph.style))
    return all(run.bold or (run.bold is None and style_bold) for run in runs)


def _textbox_texts(paragraph: Paragraph) -> list[str]:
    """Cuadros de texto del párrafo; la copia de mc:Fallback se ignora para no duplicar."""
    texts = []
    for box in paragraph._p.iter(qn("w:txbxContent")):
        if any(ancestor.tag == _MC_FALLBACK for ancestor in box.iterancestors()):
            continue
        lines = ["".join(t.text or "" for t in p.iter(qn("w:t"))) for p in box.iter(qn("w:p"))]
        text = normalize_text(" ".join(line for line in lines if line.strip()))
        if text:
            texts.append(text)
    return texts


def _header_texts(document: DocxDocument) -> list[str]:
    texts = []
    for section in document.sections:
        for header in (section.header, section.first_page_header):
            if header.is_linked_to_previous:
                continue
            texts.extend(normalize_text(p.text) for p in header.paragraphs if p.text.strip())
    return texts


def _metadata(document: DocxDocument, path: Path) -> dict[str, Any]:
    core = document.core_properties
    metadata: dict[str, Any] = {
        key: value
        for key, value in {
            "title": core.title,
            "subject": core.subject,
            "keywords": core.keywords,
        }.items()
        if value
    }
    custom = custom_properties(path)
    if custom:
        metadata["custom_properties"] = custom
    return metadata
