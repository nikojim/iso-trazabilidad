from app.ingestion.ocr_detect import requires_ocr, scanned_pages
from app.ingestion.types import PageStats


def page(number: int, chars: int, coverage: float) -> PageStats:
    return PageStats(number=number, char_count=chars, image_coverage=coverage)


def test_fully_scanned_document_requires_ocr() -> None:
    pages = [page(1, 0, 1.0), page(2, 3, 0.95)]

    assert requires_ocr(pages)
    assert scanned_pages(pages) == [1, 2]


def test_intentional_blank_page_is_not_scanned() -> None:
    pages = [page(1, 800, 0.1), page(2, 0, 0.0), page(3, 900, 0.0)]

    assert scanned_pages(pages) == []
    assert not requires_ocr(pages)


def test_partially_scanned_document_does_not_require_ocr_as_a_whole() -> None:
    pages = [page(1, 900, 0.0), page(2, 0, 1.0), page(3, 700, 0.0)]

    assert scanned_pages(pages) == [2]
    assert not requires_ocr(pages)


def test_document_without_any_text_requires_ocr() -> None:
    assert requires_ocr([page(1, 0, 0.0)])
