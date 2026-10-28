"""Valores cerrados del dominio (ver docs/IMPLEMENTATION_PLAN.md §4)."""

from enum import StrEnum


class FileFormat(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    XLSM = "xlsm"  # planilla con macros: se lee igual que XLSX
    XLS = "xls"  # formato binario anterior a 2007: solo se identifica por el nombre


# Planillas: se pueden citar, pero no se analizan sus referencias salientes.
SPREADSHEET_FORMATS = frozenset({FileFormat.XLSX, FileFormat.XLSM, FileFormat.XLS})


class ExtractionStatus(StrEnum):
    OK = "ok"
    NO_REFERENCES = "no_references"
    NO_SECTION = "no_section"
    NEEDS_REVIEW = "needs_review"
    REQUIRES_OCR = "requires_ocr"
    ERROR = "error"
    SOURCE_CODE_UNRESOLVED = "source_code_unresolved"
    # Planilla: puede ser citada, pero no se analizan sus referencias salientes.
    NOT_APPLICABLE = "not_applicable"


class CodeSource(StrEnum):
    FILENAME = "filename"
    CONTENT = "content"
    FILENAME_AND_CONTENT = "filename+content"
    OVERRIDE = "override"


class RunMode(StrEnum):
    FULL = "full"
    INCREMENTAL = "incremental"
    SINGLE = "single"


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
