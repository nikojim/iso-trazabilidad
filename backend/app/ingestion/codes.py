"""Identificación de códigos documentales dentro de un texto normalizado."""

import re
from dataclasses import dataclass

# Contrato del SKILL: código entre corchetes.
REFERENCE_PATTERN = re.compile(
    r"\[\s*([A-Z]{2,4}-[A-Z0-9]{2,5}-\d{3,5})\s*\]",
    re.IGNORECASE,
)
# Excepción acordada para la sección REFERENCIAS: código válido sin corchetes que ocupa una
# celda entera o empieza la línea (p. ej. una tabla "ES-SGG-003 | Especificaciones…").
LEADING_CODE_PATTERN = re.compile(
    r"^\s*([A-Z]{2,4}-[A-Z0-9]{2,5}-\d{3,5})(?![\w\]-])",
    re.IGNORECASE,
)
CODE_PATTERN = re.compile(r"^[A-Z]{2,4}-[A-Z0-9]{2,5}-\d{3,5}$")
_BRACKETED = re.compile(r"\[([^\[\]]{2,40})\]")
# Algo con forma de código sin corchetes (incluye variantes mal escritas como C-SGSA-915).
_CODE_LIKE = re.compile(r"(?<![\w\[-])[A-Z]{1,5}-[A-Z0-9]{1,6}-\d{1,6}[A-Z]?(?![\w\]-])")
_LETTER = re.compile(r"[A-Za-z]")
_TITLE_SEPARATORS = " -:–—|"


@dataclass(frozen=True, slots=True)
class CodeMatch:
    code: str
    raw: str
    start: int
    end: int
    title_hint: str | None
    bracketed: bool = True


@dataclass(frozen=True, slots=True)
class CandidateMatch:
    """Texto con apariencia de código que no cumple el patrón de referencia."""

    raw: str
    bracketed: bool
    well_formed: bool  # el contenido es un código válido, pero le faltan los corchetes


def split_code(code: str) -> tuple[str, str]:
    """``"PO-SGS-400"`` -> ``("PO", "SGS")``: tipo por prefijo y sistema de gestión."""
    document_type, system_code, _ = code.split("-")
    return document_type, system_code


def find_codes(text: str, *, allow_leading_unbracketed: bool = False) -> list[CodeMatch]:
    """Códigos válidos con el título que los sigue en la misma línea.

    Por defecto solo cuentan los códigos entre corchetes. Con ``allow_leading_unbracketed``
    (únicamente dentro de REFERENCIAS) también cuenta un código sin corchetes al inicio.
    """
    spans = [
        (m.start(), m.end(), m.group(1), m.group(0), True) for m in REFERENCE_PATTERN.finditer(text)
    ]
    if allow_leading_unbracketed:
        leading = LEADING_CODE_PATTERN.match(text)
        if leading:
            spans.append(
                (leading.start(1), leading.end(1), leading.group(1), leading.group(1), False)
            )
    spans.sort()

    found = []
    for i, (start, end, code, raw, bracketed) in enumerate(spans):
        tail_end = spans[i + 1][0] if i + 1 < len(spans) else len(text)
        tail = text[end:tail_end].strip(_TITLE_SEPARATORS)
        found.append(
            CodeMatch(
                code=code.upper(),
                raw=raw,
                start=start,
                end=end,
                title_hint=tail if _LETTER.search(tail) else None,
                bracketed=bracketed,
            )
        )
    return found


def find_candidates(text: str, *, allow_leading_unbracketed: bool = False) -> list[CandidateMatch]:
    """Textos que parecen códigos pero no se aceptan como referencia."""
    accepted = [
        (m.start, m.end)
        for m in find_codes(text, allow_leading_unbracketed=allow_leading_unbracketed)
    ]

    def inside_accepted(pos: int) -> bool:
        return any(start <= pos < end for start, end in accepted)

    candidates = []
    for match in _BRACKETED.finditer(text):
        if inside_accepted(match.start()):
            continue
        inner = match.group(1).strip()
        if "-" in inner and any(ch.isdigit() for ch in inner):
            candidates.append(CandidateMatch(raw=match.group(0), bracketed=True, well_formed=False))
    for match in _CODE_LIKE.finditer(text):
        if inside_accepted(match.start()):
            continue
        raw = match.group(0)
        candidates.append(
            CandidateMatch(raw=raw, bracketed=False, well_formed=bool(CODE_PATTERN.match(raw)))
        )
    return candidates
