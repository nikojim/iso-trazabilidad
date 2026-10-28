"""Huella de las reglas de extracción (ingestion/fingerprint.py)."""

from app.ingestion.config import ExtractionConfig
from app.ingestion.fingerprint import extraction_fingerprint


def test_same_rules_give_the_same_fingerprint() -> None:
    first = extraction_fingerprint(ExtractionConfig())

    assert first == extraction_fingerprint(ExtractionConfig())
    assert len(first) == 64


def test_fingerprint_ignores_the_order_of_configured_headings() -> None:
    a = ExtractionConfig(terminators=frozenset({"anexos", "historial", "registros"}))
    b = ExtractionConfig(terminators=frozenset({"registros", "anexos", "historial"}))

    assert extraction_fingerprint(a) == extraction_fingerprint(b)


def test_any_configuration_change_changes_the_fingerprint() -> None:
    base = extraction_fingerprint(ExtractionConfig())
    default = ExtractionConfig()

    assert base != extraction_fingerprint(
        ExtractionConfig(terminators=default.terminators | {"glosario"})
    )
    assert base != extraction_fingerprint(
        ExtractionConfig(section_aliases=frozenset({"referencias", "documentos de referencia"}))
    )
    assert base != extraction_fingerprint(
        ExtractionConfig(subgroups={"procedimientos": "procedimientos", "registros": "registros"})
    )
