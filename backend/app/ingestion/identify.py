"""Identificación del código, versión y título del documento de origen.

Regla (CLAUDE.md, regla 2): el código nunca se infiere de una referencia saliente. Fuentes:
nombre de archivo con la convención ``CODE-VV Título.ext``, campo de portada
``Referencia/Versión``, encabezado de página ``CODE / VV - Título - Página N/M`` y la
propiedad personalizada ``Referencia`` de Word. Si se contradicen, no se publica nada.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from app.ingestion.codes import CODE_PATTERN
from app.ingestion.normalize import normalize_text, strip_accents
from app.ingestion.types import DocumentContent, Issue, SourceIdentity, TextBlock
from app.models.enums import CodeSource, Severity

_CODE = r"[A-Z]{2,4}-[A-Z0-9]{2,5}-\d{3,5}"
_FILENAME = re.compile(rf"^({_CODE})(?:-(\d{{1,3}}))?(?=$|[\s_.])", re.IGNORECASE)
_FILENAME_FILE_REVISION = re.compile(r"\s+v\d+$", re.IGNORECASE)
_COVER_FIELD = re.compile(
    rf"REFERENCIA\s*/\s*VERSION\s*:?\s*({_CODE})(?:\s*/\s*(\d{{1,3}}))?", re.IGNORECASE
)
_COVER_LABEL = re.compile(r"REFERENCIA\s*/\s*VERSION", re.IGNORECASE)
_COVER_VALUE = re.compile(rf"^\s*({_CODE})\s*/\s*(\d{{1,3}})\s*$", re.IGNORECASE)
_PAGE_HEADER = re.compile(
    rf"^({_CODE})\s*/\s*(\d{{1,3}})\s*-\s*(.+?)\s*-\s*PAGINA\s+\d+", re.IGNORECASE
)
_COVER_NAME = re.compile(r"^NOMBRE\s*:?\s+(.{3,})$", re.IGNORECASE)
_COVER_KIND = re.compile(r"^TIPO DE DOCUMENTO\s*:?\s+(.{3,})$", re.IGNORECASE)
_CODE_PROPERTIES = {"referencia", "codigo", "code"}
_VERSION_PROPERTIES = {"version", "versión"}
_COVER_PAGES = 3  # páginas iniciales donde se buscan portada y encabezado (PDF)
_COVER_BLOCKS = 120  # bloques iniciales equivalentes en DOCX (sin paginación)


@dataclass(frozen=True, slots=True)
class _Evidence:
    source: str
    code: str
    version: str | None


def identify_source(
    path: Path, content: DocumentContent, code_override: str | None = None
) -> SourceIdentity:
    file_code, file_version, file_title = _from_filename(path)
    cover_rows = list(_cover_rows(content.blocks))
    evidence = list(_content_evidence(cover_rows, content))
    content_codes = {e.code for e in evidence}
    content_version = next((e.version for e in evidence if e.version), None)
    title = _title(cover_rows, content) or file_title or content.metadata.get("title")
    kind = _first_match(_COVER_KIND, cover_rows)
    issues: list[Issue] = []

    def identity(code: str | None, source: CodeSource | None) -> SourceIdentity:
        version = content_version or file_version
        # Comparar versiones solo tiene sentido si nombre y contenido hablan del mismo documento.
        same_document = code is not None and source is not CodeSource.OVERRIDE
        if (
            same_document
            and file_version
            and content_version
            and int(file_version) != int(content_version)
        ):
            issues.append(
                Issue(
                    "version_mismatch",
                    Severity.WARNING,
                    f"La versión del nombre ({file_version}) difiere de la del contenido "
                    f"({content_version})",
                    {"filename": file_version, "content": content_version},
                )
            )
        return SourceIdentity(code, version, title, source, kind, tuple(issues))

    if code_override:
        override = code_override.strip().upper()
        if not CODE_PATTERN.match(override):
            issues.append(
                Issue(
                    "source_code_missing",
                    Severity.ERROR,
                    f"El código indicado manualmente no es válido: {code_override}",
                )
            )
            return identity(None, None)
        return identity(override, CodeSource.OVERRIDE)

    if len(content_codes) > 1:
        issues.append(_conflict("El contenido declara más de un código", evidence, file_code))
        return identity(None, None)
    content_code = next(iter(content_codes), None)

    if file_code and content_code:
        if file_code == content_code:
            return identity(file_code, CodeSource.FILENAME_AND_CONTENT)
        issues.append(
            _conflict("El código del nombre no coincide con el contenido", evidence, file_code)
        )
        return identity(None, None)
    if file_code:
        return identity(file_code, CodeSource.FILENAME)
    if content_code and len({e.source for e in evidence}) >= 2:
        return identity(content_code, CodeSource.CONTENT)

    issues.append(
        Issue(
            "source_code_missing",
            Severity.ERROR,
            "No se pudo identificar el código del documento con suficiente certeza",
            {"content_evidence": [e.source for e in evidence]},
        )
    )
    return identity(None, None)


def _from_filename(path: Path) -> tuple[str | None, str | None, str | None]:
    match = _FILENAME.match(path.stem)
    if not match:
        return None, None, None
    rest = normalize_text(path.stem[match.end() :]).strip(" -_")
    rest = _FILENAME_FILE_REVISION.sub("", rest)
    return match.group(1).upper(), match.group(2), rest or None


def _cover_rows(blocks: list[TextBlock]) -> Iterable[str]:
    """Líneas iniciales; en DOCX las celdas de una misma fila se unen en un solo texto."""
    row_key: tuple[int, int] | None = None
    row_parts: list[str] = []
    for position, block in enumerate(blocks):
        if block.page is not None and block.page > _COVER_PAGES:
            break
        if block.page is None and position >= _COVER_BLOCKS:
            break
        key = (
            (block.table_index, block.row_index)
            if block.table_index is not None and block.row_index is not None
            else None
        )
        if key is not None and key == row_key:
            row_parts.append(block.text)
            continue
        if row_parts:
            yield " ".join(row_parts)
        row_key, row_parts = key, [block.text]
    if row_parts:
        yield " ".join(row_parts)


def _cover_field(rows: list[str]) -> _Evidence | None:
    for index, row in enumerate(rows):
        plain = strip_accents(row)
        match = _COVER_FIELD.search(plain)
        if match:
            return _Evidence("cover", match.group(1).upper(), match.group(2))
        if _COVER_LABEL.search(plain):
            # Celda de valor desalineada respecto de la etiqueta: buscar en las líneas vecinas.
            for neighbor in rows[max(index - 1, 0) : index + 2]:
                value = _COVER_VALUE.match(neighbor)
                if value:
                    return _Evidence("cover", value.group(1).upper(), value.group(2))
    return None


def _content_evidence(rows: list[str], content: DocumentContent) -> Iterable[_Evidence]:
    cover = _cover_field(rows)
    if cover:
        yield cover
    header_lines = [*rows, *content.header_texts]
    for line in header_lines:
        match = _PAGE_HEADER.match(strip_accents(line))
        if match:
            yield _Evidence("page_header", match.group(1).upper(), match.group(2))
            break
    properties = {
        strip_accents(k).casefold(): v
        for k, v in content.metadata.get("custom_properties", {}).items()
    }
    for name in _CODE_PROPERTIES:
        value = properties.get(name, "").strip().upper()
        if CODE_PATTERN.match(value):
            version = next((properties[v] for v in _VERSION_PROPERTIES if properties.get(v)), None)
            yield _Evidence("custom_property", value, version)
            break


def _title(rows: list[str], content: DocumentContent) -> str | None:
    for line in [*rows, *content.header_texts]:
        match = _PAGE_HEADER.match(strip_accents(line))
        if match:
            # Recortar sobre el texto original para conservar las tildes.
            return line[match.start(3) : match.end(3)]
    return _first_match(_COVER_NAME, rows)


def _first_match(pattern: re.Pattern[str], rows: list[str]) -> str | None:
    for row in rows:
        match = pattern.match(strip_accents(row))
        if match:
            return row[match.start(1) : match.end(1)].strip()
    return None


def _conflict(message: str, evidence: list[_Evidence], file_code: str | None) -> Issue:
    return Issue(
        "source_code_conflict",
        Severity.ERROR,
        message,
        {"filename": file_code, "content": {e.source: e.code for e in evidence}},
    )
