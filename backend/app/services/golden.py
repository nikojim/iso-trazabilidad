"""Set de referencia (golden): referencias anotadas a mano para medir precisión y recall.

Formato CSV (UTF-8, separador ``;``), una fila por relación esperada::

    file;target_code;group;note
    SGSA ISO 20000/MC-SGG-435-23 Manual.pdf;ES-SGC-001;general;
    SGSA ISO 20000/LC-SGSA-915-01 Listado.pdf;;;sin referencias

``file`` es relativo al directorio de muestras. Una fila con ``target_code`` vacío declara un
documento anotado que no debe tener referencias. Solo se evalúan los archivos del CSV.
"""

import csv
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from app.ingestion.types import ExtractionResult
from app.models.enums import ExtractionStatus

COLUMNS = ["file", "target_code", "group", "note"]
PUBLISHABLE = {ExtractionStatus.OK, ExtractionStatus.NO_REFERENCES, ExtractionStatus.NO_SECTION}


class GoldenFormatError(ValueError):
    """El CSV del set de referencia no tiene el formato esperado."""


@dataclass
class FileResult:
    file: str
    status: str
    expected: dict[str, str]  # código → grupo
    actual: dict[str, str]

    @property
    def true_positives(self) -> set[str]:
        return set(self.expected) & set(self.actual)

    @property
    def false_positives(self) -> set[str]:
        return set(self.actual) - set(self.expected)

    @property
    def false_negatives(self) -> set[str]:
        return set(self.expected) - set(self.actual)

    @property
    def group_mismatches(self) -> set[str]:
        return {c for c in self.true_positives if self.expected[c] != self.actual[c]}


@dataclass
class GoldenReport:
    files: list[FileResult] = field(default_factory=list)

    def _total(self, attribute: str) -> int:
        return sum(len(getattr(f, attribute)) for f in self.files)

    @property
    def true_positives(self) -> int:
        return self._total("true_positives")

    @property
    def false_positives(self) -> int:
        return self._total("false_positives")

    @property
    def false_negatives(self) -> int:
        return self._total("false_negatives")

    @property
    def group_mismatches(self) -> int:
        return self._total("group_mismatches")

    @property
    def precision(self) -> float:
        found = self.true_positives + self.false_positives
        return self.true_positives / found if found else 1.0

    @property
    def recall(self) -> float:
        expected = self.true_positives + self.false_negatives
        return self.true_positives / expected if expected else 1.0

    @property
    def group_accuracy(self) -> float:
        return 1 - self.group_mismatches / self.true_positives if self.true_positives else 1.0

    def meets(self, min_precision: float, min_recall: float) -> bool:
        return self.precision >= min_precision and self.recall >= min_recall


def load_golden(path: Path) -> dict[str, dict[str, str]]:
    """Archivo → {código esperado: grupo}."""
    expected: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        missing = {"file", "target_code"} - set(reader.fieldnames or [])
        if missing:
            raise GoldenFormatError(f"Faltan columnas en {path.name}: {', '.join(sorted(missing))}")
        for line, row in enumerate(reader, start=2):
            file = (row.get("file") or "").strip().replace("\\", "/")
            if not file:
                raise GoldenFormatError(f"Línea {line}: falta la columna file")
            codes = expected.setdefault(file, {})
            code = (row.get("target_code") or "").strip().upper()
            if code:
                codes[code] = (row.get("group") or "general").strip() or "general"
    return expected


def actual_references(result: ExtractionResult) -> dict[str, str]:
    """Lo que se publicaría: si no hay certeza sobre la sección, no se cuenta nada."""
    if result.status not in PUBLISHABLE:
        return {}
    return {reference.code: reference.group for reference in result.references}


def evaluate(
    expected: dict[str, dict[str, str]],
    samples_dir: Path,
    extract: Callable[[Path], ExtractionResult],
) -> GoldenReport:
    report = GoldenReport()
    for file, codes in sorted(expected.items()):
        path = samples_dir / file
        if not path.is_file():
            report.files.append(FileResult(file, "missing_file", codes, {}))
            continue
        result = extract(path)
        report.files.append(FileResult(file, result.status.value, codes, actual_references(result)))
    return report


def draft_rows(results: Iterable[tuple[str, ExtractionResult]]) -> list[dict[str, str]]:
    """Borrador para anotar a mano: lo que extrae hoy el sistema, a revisar fila por fila."""
    rows: list[dict[str, str]] = []
    for file, result in results:
        note = "" if result.status in PUBLISHABLE else f"REVISAR: {result.status.value}"
        if not result.references:
            rows.append(
                {"file": file, "target_code": "", "group": "", "note": note or "sin referencias"}
            )
        for reference in result.references:
            rows.append(
                {
                    "file": file,
                    "target_code": reference.code,
                    "group": reference.group,
                    "note": note,
                }
            )
    return rows


def write_rows(rows: list[dict[str, str]], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, delimiter=";", lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
