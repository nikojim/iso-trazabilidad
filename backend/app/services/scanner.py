"""Recorrido del directorio de documentos, hashing y sanitización de rutas."""

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.ingestion.readers import detect_format
from app.models.enums import FileFormat

_HASH_CHUNK = 1024 * 1024


class PathOutsideRootError(ValueError):
    """La ruta pedida está fuera del directorio de documentos configurado."""


@dataclass(frozen=True, slots=True)
class ScannedFile:
    path: Path  # absoluta y resuelta
    rel_path: str  # relativa a la raíz, siempre con "/"
    file_format: FileFormat
    size: int
    mtime: datetime

    @property
    def folder(self) -> str:
        parent = Path(self.rel_path).parent.as_posix()
        return "" if parent == "." else parent

    @property
    def norma(self) -> str | None:
        """Carpeta raíz (la norma); ``None`` para un archivo suelto en la raíz."""
        head, separator, _ = self.rel_path.partition("/")
        return head if separator else None


@dataclass(slots=True)
class ScanResult:
    files: list[ScannedFile]
    unsupported_count: int
    root_files: list[str]  # sueltos en la raíz: no pertenecen a ninguna norma


def resolve_within(path: Path, root: Path) -> Path:
    """Resuelve ``path`` y exige que quede dentro de ``root`` (sin escapar con ``..``)."""
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise PathOutsideRootError(f"{path} está fuera del directorio de documentos {root}")
    return resolved


def relative_path(path: Path, root: Path) -> str:
    return resolve_within(path, root).relative_to(root.resolve()).as_posix()


def is_ignored(path: Path) -> bool:
    """Temporales de Office (``~$…``) y archivos o carpetas ocultos."""
    return path.name.startswith(("~$", "."))


def describe_file(path: Path, root: Path) -> ScannedFile | None:
    """Datos de un archivo soportado, o ``None`` si no es procesable o debe ignorarse."""
    resolved = resolve_within(path, root)
    file_format = detect_format(resolved)
    if file_format is None or is_ignored(resolved):
        return None
    stat = resolved.stat()
    return ScannedFile(
        path=resolved,
        rel_path=relative_path(resolved, root),
        file_format=file_format,
        size=stat.st_size,
        mtime=datetime.fromtimestamp(stat.st_mtime, UTC),
    )


def scan(path: Path, root: Path) -> ScanResult:
    """Lista recursivamente los PDF/DOCX/planilla Excel bajo ``path`` en orden determinista."""
    base = resolve_within(path, root)
    files: list[ScannedFile] = []
    root_files: list[str] = []
    unsupported = 0
    for candidate in _walk(base):
        if is_ignored(candidate):
            continue  # temporales y ocultos no cuentan ni como no soportados
        described = describe_file(candidate, root)
        if described is None:
            unsupported += 1
        elif described.norma is None:
            root_files.append(described.rel_path)
        else:
            files.append(described)
    return ScanResult(sorted(files, key=lambda f: f.rel_path), unsupported, sorted(root_files))


def _walk(base: Path) -> Iterator[Path]:
    if base.is_file():
        yield base
        return
    for candidate in sorted(base.rglob("*")):
        hidden_folder = any(is_ignored(p) for p in candidate.relative_to(base).parents if p.name)
        if candidate.is_file() and not hidden_folder:
            yield candidate


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()
