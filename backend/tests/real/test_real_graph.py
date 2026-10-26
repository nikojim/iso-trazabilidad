"""Grafo e impacto sobre los documentos reales (``ISO_REAL_SAMPLES_DIR``; nunca versionados)."""

import os
from pathlib import Path

import pytest
from sqlalchemy import Engine

from app.db.session import make_session_factory
from app.ingestion.config import ExtractionConfig
from app.services.graph import build_graph, find_cycles, node_key, norma_names
from app.services.impact import impacted_by
from app.services.ingest import IngestionService, IngestOptions
from app.services.validation import derived_issues

pytestmark = pytest.mark.real_docs
SGSA = "SGSA ISO 20000"


@pytest.fixture
def samples(migrated_engine: Engine) -> Engine:
    value = os.environ.get("ISO_REAL_SAMPLES_DIR")
    if not value or not (Path(value) / SGSA).is_dir():
        pytest.skip("ISO_REAL_SAMPLES_DIR no tiene la carpeta SGSA ISO 20000")
    IngestionService(migrated_engine, Path(value), ExtractionConfig()).ingest_path(
        Path(value), IngestOptions()
    )
    return migrated_engine


def test_each_root_folder_is_a_norma(samples: Engine) -> None:
    with make_session_factory(samples)() as session:
        assert SGSA in norma_names(session)


def test_real_cycles_and_impact(samples: Engine) -> None:
    with make_session_factory(samples)() as session:
        graph = build_graph(session)

    cycle = [node_key(SGSA, "ES-SGSA-919"), node_key(SGSA, "PC-SGSA-914")]
    assert cycle in find_cycles(graph, limit=10_000)
    impact = impacted_by(graph, node_key(SGSA, "PC-SGSA-914"), 1, max_depth=10)
    assert {"PO-SGSA-918", "ES-SGSA-919"} <= {item.code for item in impact.direct}


def test_real_suggestion_for_wrong_prefix(samples: Engine) -> None:
    with make_session_factory(samples)() as session:
        similar = [i for i in derived_issues(session) if i.type == "unresolved_similar_code"]

    assert any(
        i.code == "RG-SGSA-928" and i.details["candidates"] == ["LC-SGSA-928"] for i in similar
    )
