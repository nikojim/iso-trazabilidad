"""Lectura de PDF con PyMuPDF: líneas visuales en orden, con página y formato."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf

from app.ingestion.furniture import mark_furniture
from app.ingestion.normalize import normalize_text
from app.ingestion.readers import EncryptedDocumentError, ReadError
from app.ingestion.types import BlockKind, Bookmark, DocumentContent, PageStats, TextBlock
from app.models.enums import FileFormat

BASELINE_TOLERANCE = 2.0  # puntos: spans con líneas base más cercanas forman una misma línea
_BOLD_FONT = re.compile(r"bold|black|heavy|semibold|demi", re.IGNORECASE)
_BOLD_FLAG = 1 << 4


@dataclass(slots=True)
class _Span:
    text: str
    baseline: float
    x0: float
    x1: float
    y0: float
    y1: float
    size: float
    bold: bool


def read_pdf(path: Path) -> DocumentContent:
    try:
        document = pymupdf.open(path)
    except (pymupdf.FileDataError, RuntimeError) as exc:
        raise ReadError(f"No se pudo abrir el PDF: {exc}") from exc
    with document:
        if document.needs_pass:
            raise EncryptedDocumentError("El PDF está protegido con contraseña")
        blocks: list[TextBlock] = []
        images: dict[int, float] = {}
        heights: dict[int, float] = {}
        for page in document:
            number = page.number + 1
            heights[number] = page.rect.height
            images[number] = _image_coverage(page)
            blocks.extend(_page_lines(page, number))
        blocks = mark_furniture(blocks, heights, document.page_count)
        return DocumentContent(
            file_format=FileFormat.PDF,
            blocks=blocks,
            page_count=document.page_count,
            pages=_page_stats(blocks, images),
            bookmarks=[
                Bookmark(level=level, title=normalize_text(title), page=page)
                for level, title, page, *_ in document.get_toc(simple=True)
            ],
            metadata={k: v for k, v in (document.metadata or {}).items() if v},
        )


def _page_lines(page: Any, number: int) -> list[TextBlock]:
    spans = sorted(_horizontal_spans(page), key=lambda s: (s.baseline, s.x0))
    clusters: list[list[_Span]] = []
    for span in spans:
        if clusters and abs(span.baseline - clusters[-1][0].baseline) <= BASELINE_TOLERANCE:
            clusters[-1].append(span)
        else:
            clusters.append([span])
    return [_line_block(cluster, number) for cluster in clusters]


def _horizontal_spans(page: Any) -> list[_Span]:
    spans = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            # Texto rotado (p. ej. la marca vertical "CONFIDENCIAL") no forma parte del cuerpo.
            if abs(line["dir"][0] - 1) > 0.01 or abs(line["dir"][1]) > 0.01:
                continue
            for span in line["spans"]:
                if not span["text"].strip():
                    continue
                x0, y0, x1, y1 = span["bbox"]
                spans.append(
                    _Span(
                        text=span["text"],
                        baseline=span["origin"][1],
                        x0=x0,
                        x1=x1,
                        y0=y0,
                        y1=y1,
                        size=span["size"],
                        bold=bool(span["flags"] & _BOLD_FLAG)
                        or bool(_BOLD_FONT.search(span["font"])),
                    )
                )
    return spans


def _line_block(cluster: list[_Span], number: int) -> TextBlock:
    cluster.sort(key=lambda s: s.x0)
    parts = [cluster[0].text]
    for previous, span in zip(cluster, cluster[1:], strict=False):
        gap = span.x0 - previous.x1
        parts.append(" " + span.text if gap > 1.0 else span.text)
    raw = "".join(parts)
    return TextBlock(
        text=normalize_text(raw),
        raw_text=raw,
        kind=BlockKind.LINE,
        page=number,
        is_bold=all(span.bold for span in cluster),
        font_size=max(span.size for span in cluster),
        bbox=(
            min(s.x0 for s in cluster),
            min(s.y0 for s in cluster),
            max(s.x1 for s in cluster),
            max(s.y1 for s in cluster),
        ),
    )


def _image_coverage(page: Any) -> float:
    page_area = page.rect.width * page.rect.height or 1.0
    covered = 0.0
    for info in page.get_image_info():
        rect = pymupdf.Rect(info["bbox"]) & page.rect
        if not rect.is_empty:
            covered += rect.width * rect.height
    return min(covered / page_area, 1.0)


def _page_stats(blocks: list[TextBlock], images: dict[int, float]) -> list[PageStats]:
    chars = dict.fromkeys(images, 0)
    for block in blocks:
        if block.page is not None and not block.is_furniture:
            chars[block.page] += sum(1 for ch in block.text if not ch.isspace())
    return [PageStats(number=n, char_count=chars[n], image_coverage=images[n]) for n in images]
