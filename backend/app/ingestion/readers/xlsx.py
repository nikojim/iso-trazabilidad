"""Lectura de planillas XLSX con openpyxl: solo identidad (no se analizan referencias salientes).

Una planilla puede ser citada por otros documentos, pero no tiene sección REFERENCIAS: el
lector devuelve un contenido sin bloques, con las propiedades del libro y la cantidad de hojas.
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


def read_xlsx(path: Path) -> DocumentContent:
    with path.open("rb") as handle:
        if handle.read(len(_OLE_SIGNATURE)) == _OLE_SIGNATURE:
            raise EncryptedDocumentError("La planilla está protegida con contraseña")
    try:
        workbook = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    except (InvalidFileException, zipfile.BadZipFile, KeyError, ValueError, OSError) as exc:
        raise ReadError(f"No se pudo abrir el XLSX: {exc}") from exc
    try:
        return DocumentContent(
            file_format=FileFormat.XLSX,
            blocks=[],
            page_count=None,
            metadata=_metadata(workbook, path),
        )
    finally:
        workbook.close()


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
