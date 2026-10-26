"""Lectores de documentos: convierten un archivo en una secuencia ordenada de TextBlock."""

from pathlib import Path

from app.ingestion.types import DocumentContent
from app.models.enums import FileFormat


class ReadError(Exception):
    """El archivo no se pudo leer (corrupto, formato inválido, etc.)."""


class EncryptedDocumentError(ReadError):
    """El archivo está protegido con contraseña."""


SUPPORTED_SUFFIXES = {
    ".pdf": FileFormat.PDF,
    ".docx": FileFormat.DOCX,
    ".xlsx": FileFormat.XLSX,
}


def detect_format(path: Path) -> FileFormat | None:
    return SUPPORTED_SUFFIXES.get(path.suffix.lower())


def read_document(path: Path) -> DocumentContent:
    file_format = detect_format(path)
    if file_format is FileFormat.PDF:
        from app.ingestion.readers.pdf import read_pdf

        return read_pdf(path)
    if file_format is FileFormat.DOCX:
        from app.ingestion.readers.docx import read_docx

        return read_docx(path)
    if file_format is FileFormat.XLSX:
        from app.ingestion.readers.xlsx import read_xlsx

        return read_xlsx(path)
    raise ReadError(f"Formato no soportado: {path.suffix or '(sin extensión)'}")
