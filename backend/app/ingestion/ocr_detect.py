"""Heurística para detectar PDF escaneados o sin texto utilizable."""

from app.ingestion.types import PageStats

MIN_TEXT_CHARS = 25
MIN_IMAGE_COVERAGE = 0.5
SCANNED_DOCUMENT_RATIO = 0.8


def scanned_pages(pages: list[PageStats]) -> list[int]:
    """Páginas con casi nada de texto y cubiertas mayormente por imágenes.

    Una página en blanco intencional (sin imágenes) no cuenta como escaneada.
    """
    return [
        page.number
        for page in pages
        if page.char_count < MIN_TEXT_CHARS and page.image_coverage >= MIN_IMAGE_COVERAGE
    ]


def requires_ocr(pages: list[PageStats]) -> bool:
    if not pages:
        return False
    if sum(page.char_count for page in pages) == 0:
        return True
    return len(scanned_pages(pages)) >= SCANNED_DOCUMENT_RATIO * len(pages)
