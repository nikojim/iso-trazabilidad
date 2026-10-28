"""Elección de la edición vigente cuando un mismo código aparece en varios archivos de una norma.

Regla acordada con el usuario (2026-10-23):
- Copias idénticas (mismo SHA-256): se reconocen como copia (``duplicate_copy``).
- Vigente: la de mayor versión, siempre que ninguna versión menor tenga una fecha de
  modificación más reciente. A igual versión, el formato preferido (PDF, DOCX, XLSX, XLSM, XLS).
- Si versión y fecha no coinciden (p. ej. informes periódicos donde la versión se reinicia
  cada año), la elección es ambigua: no se publica ninguna (``ambiguous_editions``).
"""

from dataclasses import dataclass
from datetime import datetime

from app.ingestion.types import Issue
from app.models import FileFormat, Severity

# El PDF publicado gana al Word fuente; la planilla, que no aporta referencias, va al final.
FORMAT_PRIORITY = (
    FileFormat.PDF,
    FileFormat.DOCX,
    FileFormat.XLSX,
    FileFormat.XLSM,
    FileFormat.XLS,
)


@dataclass(frozen=True, slots=True)
class Edition:
    path: str
    version: str | None
    file_format: FileFormat
    mtime: datetime
    sha256: str

    @property
    def version_number(self) -> int:
        return int(self.version) if self.version and self.version.isdigit() else -1


@dataclass(slots=True)
class EditionChoice:
    current: Edition | None  # None: elección ambigua, no se publica ninguna
    issues: dict[str, Issue]  # por ruta, para cada archivo que no es la edición vigente


def choose_edition(code: str, editions: list[Edition]) -> EditionChoice:
    issues: dict[str, Issue] = {}
    distinct: dict[str, Edition] = {}
    for edition in sorted(editions, key=lambda e: e.path):
        kept = distinct.setdefault(edition.sha256, edition)
        if kept is not edition:
            issues[edition.path] = Issue(
                "duplicate_copy",
                Severity.INFO,
                f"{edition.path} es una copia idéntica de {kept.path}",
                {"code": code, "kept": kept.path, "other": edition.path},
            )
    candidates = list(distinct.values())
    current = _unambiguous_current(candidates)
    if current is None:
        details = {
            "code": code,
            "editions": [
                {"path": e.path, "version": e.version, "modified": e.mtime.isoformat()}
                for e in sorted(candidates, key=lambda e: e.mtime)
            ],
        }
        for edition in candidates:
            issues[edition.path] = Issue(
                "ambiguous_editions",
                Severity.ERROR,
                f"{code} tiene varias ediciones y versión y fecha no coinciden en cuál es la "
                "vigente; no se publica ninguna hasta resolverlo (dejar solo la vigente o "
                "usar ingest-file --replace)",
                details,
            )
        return EditionChoice(None, issues)

    for edition in candidates:
        if edition is current:
            continue
        details = {"code": code, "kept": current.path, "other": edition.path}
        if edition.version_number == current.version_number:
            issues[edition.path] = Issue(
                "alternate_format",
                Severity.INFO,
                f"{code} existe en otro formato; se usa {current.path}",
                details,
            )
        else:
            issues[edition.path] = Issue(
                "superseded_version",
                Severity.INFO,
                f"{edition.path} es una edición anterior de {code}; la vigente es {current.path}",
                details,
            )
    return EditionChoice(current, issues)


def _unambiguous_current(candidates: list[Edition]) -> Edition | None:
    if len(candidates) == 1:
        return candidates[0]
    top_version = max(e.version_number for e in candidates)
    top = [e for e in candidates if e.version_number == top_version]
    if len({e.file_format for e in top}) < len(top):
        return None  # misma versión y mismo formato con contenido distinto
    current = min(top, key=lambda e: FORMAT_PRIORITY.index(e.file_format))
    older = [e for e in candidates if e.version_number < top_version]
    if any(e.mtime > current.mtime for e in older):
        return None  # una versión menor es más reciente: versión y fecha no coinciden
    return current
