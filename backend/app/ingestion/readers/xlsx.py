"""Lectura de planillas Excel: solo identidad (no se analizan referencias salientes).

Una planilla puede ser citada por otros documentos, pero no tiene sección REFERENCIAS: el
lector devuelve un contenido sin bloques, con las propiedades del libro y la cantidad de hojas.
XLSX y XLSM se leen con openpyxl; el XLS binario (anterior a 2007) no se abre: se identifica
solo por el nombre del archivo.
"""

import zipfile
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from app.ingestion.readers import EncryptedDocumentError, ReadError
from app.ingestion.readers.ooxml import custom_properties
from app.ingestion.types import DocumentContent
from app.models.enums import FileFormat

# Un XLSX protegido con contraseña es un contenedor OLE (CFB), no un ZIP.
_OLE_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")


def _is_ole(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(len(_OLE_SIGNATURE)) == _OLE_SIGNATURE


def read_xlsx(path: Path, file_format: FileFormat = FileFormat.XLSX) -> DocumentContent:
    if _is_ole(path):
        raise EncryptedDocumentError("La planilla está protegida con contraseña")
    try:
        workbook = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    except (InvalidFileException, zipfile.BadZipFile, KeyError, ValueError, OSError) as exc:
        raise ReadError(f"No se pudo abrir la planilla: {exc}") from exc
    try:
        return DocumentContent(
            file_format=file_format,
            blocks=[],
            page_count=None,
            metadata=_metadata(workbook, path),
        )
    finally:
        workbook.close()


def read_xls(path: Path) -> DocumentContent:
    """XLS binario: se verifica que sea un contenedor OLE y no se lee nada más."""
    if not _is_ole(path):
        raise ReadError("No es una planilla XLS válida")
    return DocumentContent(file_format=FileFormat.XLS, blocks=[], page_count=None, metadata={})


def _metadata(workbook: Any, path: Path) -> dict[str, Any]:
    properties = workbook.properties
    metadata: dict[str, Any] = {
        key: value
        for key, value in {
            "title": properties.title,
            "subject": properties.subject,
            "keywords": properties.keywords,
        }.items()
        if value
    }
    metadata["sheets"] = list(workbook.sheetnames)
    custom = custom_properties(path)
    if custom:
        metadata["custom_properties"] = custom
    return metadata
