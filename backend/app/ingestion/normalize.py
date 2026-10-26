"""Normalización de texto: Unicode, guiones, espacios y claves de encabezado."""

import re
import unicodedata

# Guiones Unicode equivalentes a "-" (además de los que NFKC ya convierte).
_DASHES = "‐‑‒–—―−﹘﹣－"
_DASH_TABLE = str.maketrans(dict.fromkeys(_DASHES, "-"))
_WHITESPACE = re.compile(r"\s+")
_LEADING_NUMBERING = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+")
_TRAILING_PUNCTUATION = re.compile(r"[\s:.;,\-]+$")


def normalize_text(text: str) -> str:
    """NFKC, guiones unificados y espacios colapsados (NBSP, tabulaciones, saltos)."""
    text = unicodedata.normalize("NFKC", text).translate(_DASH_TABLE)
    return _WHITESPACE.sub(" ", text).strip()


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def heading_key(text: str) -> str:
    """Clave comparable de un encabezado: ``"4  Referencias:"`` -> ``"referencias"``."""
    text = _LEADING_NUMBERING.sub("", normalize_text(text))
    text = _TRAILING_PUNCTUATION.sub("", text)
    return strip_accents(text).casefold()
