"""Precisión y recall contra el set de referencia anotado a mano (local, nunca versionado).

Uso::

    uv run iso-trace golden draft samples -o golden/expected.csv   # borrador, revisar a mano
    ISO_REAL_SAMPLES_DIR=samples ISO_GOLDEN_SET=golden/expected.csv uv run pytest -m real_docs
"""

import os
from pathlib import Path

import pytest

from app.ingestion.extractor import extract_document
from app.services import golden

pytestmark = pytest.mark.real_docs

MIN_PRECISION = 0.99
MIN_RECALL = 0.98


def test_golden_set_precision_and_recall() -> None:
    samples = Path(os.environ.get("ISO_REAL_SAMPLES_DIR", ""))
    golden_csv = Path(os.environ.get("ISO_GOLDEN_SET", ""))
    if not samples.is_dir() or not golden_csv.is_file():
        pytest.skip("ISO_REAL_SAMPLES_DIR o ISO_GOLDEN_SET no están configurados")

    report = golden.evaluate(golden.load_golden(golden_csv), samples, extract_document)
    failures = [
        f"{f.file}: faltan {sorted(f.false_negatives)} sobran {sorted(f.false_positives)}"
        for f in report.files
        if f.false_negatives or f.false_positives
    ]

    assert report.precision >= MIN_PRECISION, failures
    assert report.recall >= MIN_RECALL, failures
