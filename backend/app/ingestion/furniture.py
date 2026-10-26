"""Detección de encabezados y pies de página repetidos en PDF."""

import re
from collections import defaultdict
from dataclasses import replace

from app.ingestion.types import TextBlock

MARGIN_FRACTION = 0.2  # franja superior/inferior donde se buscan encabezados y pies
MIN_PAGE_SHARE = 0.5  # proporción mínima de páginas en las que debe repetirse
_DIGITS = re.compile(r"\d+")


def _key(text: str) -> str:
    # "Página 4/36" y "Página 5/36" deben considerarse la misma línea.
    return _DIGITS.sub("#", text.casefold())


def mark_furniture(
    blocks: list[TextBlock], page_heights: dict[int, float], page_count: int
) -> list[TextBlock]:
    """Marca como furniture las líneas de los márgenes que se repiten en muchas páginas."""
    if page_count < 2:
        return blocks
    threshold = max(2, MIN_PAGE_SHARE * page_count)

    def in_margin(block: TextBlock) -> bool:
        if block.bbox is None or block.page is None:
            return False
        height = page_heights[block.page]
        top, bottom = block.bbox[1], block.bbox[3]
        return bottom <= height * MARGIN_FRACTION or top >= height * (1 - MARGIN_FRACTION)

    pages_by_key: dict[str, set[int]] = defaultdict(set)
    for block in blocks:
        if in_margin(block):
            pages_by_key[_key(block.text)].add(block.page)  # type: ignore[arg-type]
    repeated = {key for key, pages in pages_by_key.items() if len(pages) >= threshold}

    return [
        replace(block, is_furniture=True)
        if in_margin(block) and _key(block.text) in repeated
        else block
        for block in blocks
    ]
