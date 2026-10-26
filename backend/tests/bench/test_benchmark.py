"""Rendimiento con 500 documentos sintéticos (docs/IMPLEMENTATION_PLAN.md, Fase 7).

Uso: ``uv run pytest -m benchmark -s``. Objetivos: ingesta completa < 5 min, incremental sin
cambios < 30 s, impacto y subgrafo p95 < 200 ms por consulta.
"""

import random
import statistics
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.api.main import create_app
from app.config import Settings
from app.ingestion.config import ExtractionConfig
from app.services.ingest import IngestionService, IngestOptions
from tests.fixtures.builders import Heading, Line, Para, build_docx, build_pdf, heading, ref

pytestmark = pytest.mark.benchmark

DOCUMENTS = 500
GRAPHS = ("Calidad", "Seguridad")
PREFIXES = ("PO", "PR", "ES", "AL", "PC", "LC", "RG", "MC")
CITATIONS = 8  # referencias por documento (más algunas a códigos sin documento)
QUERIES = 60
FULL_LIMIT_S = 300
INCREMENTAL_LIMIT_S = 30
QUERY_P95_LIMIT_MS = 200


def _corpus(root: Path) -> list[tuple[str, str]]:
    """Genera los archivos y devuelve (grafo, código) de cada documento."""
    rng = random.Random(20261024)
    codes = [
        (GRAPHS[i % len(GRAPHS)], f"{PREFIXES[i % len(PREFIXES)]}-SG{i % 7}-{100 + i}")
        for i in range(DOCUMENTS)
    ]
    by_graph = {g: [c for graph, c in codes if graph == g] for g in GRAPHS}
    for index, (graph, code) in enumerate(codes):
        cited = rng.sample(by_graph[graph], CITATIONS) + [f"AX-SGX-{rng.randint(1, 60):03d}"]
        cited = [c for c in cited if c != code]
        folder = root / graph / f"{index % 10:02d} - Carpeta"
        folder.mkdir(parents=True, exist_ok=True)
        if index % 5 == 0:
            build_docx(
                folder / f"{code}-01 Documento {index}.docx",
                [
                    Heading("OBJETIVO"),
                    Para("Texto del objetivo."),
                    Heading("REFERENCIAS"),
                    *(Para(f"[{c}]\tDocumento citado") for c in cited),
                    Heading("HISTORIAL"),
                ],
            )
        else:
            build_pdf(
                folder / f"{code}-01 Documento {index}.pdf",
                [
                    [heading("1 OBJETIVO"), Line("Texto del objetivo."), heading("4 REFERENCIAS")],
                    [*(ref(c) for c in cited), heading("5 HISTORIAL"), Line("01 Inicial")],
                ],
            )
    return codes


def _p95(samples_ms: list[float]) -> float:
    return statistics.quantiles(samples_ms, n=20)[-1]


def _timed(client: TestClient, url: str, params: dict[str, object]) -> float:
    start = time.perf_counter()
    response = client.get(url, params=params)
    elapsed = (time.perf_counter() - start) * 1000
    assert response.status_code == 200, response.text
    return elapsed


def test_benchmark_500_documents(tmp_path: Path, db_url: str, migrated_engine: Engine) -> None:
    root = tmp_path / "documents"
    start = time.perf_counter()
    codes = _corpus(root)
    generation = time.perf_counter() - start

    service = IngestionService(migrated_engine, root, ExtractionConfig())
    start = time.perf_counter()
    full = service.ingest_path(root, IngestOptions())
    full_s = time.perf_counter() - start
    start = time.perf_counter()
    again = service.ingest_path(root, IngestOptions(incremental=True))
    incremental_s = time.perf_counter() - start

    assert full.count("created") == DOCUMENTS and full.error_count == 0
    assert again.count("skipped") == DOCUMENTS

    settings = Settings(_env_file=None, database_url=db_url, documents_dir=root)
    rng = random.Random(7)
    sample = rng.sample(codes, QUERIES)
    with TestClient(create_app(settings)) as client:
        _timed(client, "/api/graphs", {})  # calienta la caché de grafos
        impact_ms = [
            _timed(client, f"/api/documents/{code}/impact", {"graph": graph, "depth": 3})
            for graph, code in sample
        ]
        graph_ms = [
            _timed(client, "/api/graph", {"code": code, "graph": graph, "depth": 2})
            for graph, code in sample
        ]

    print(
        f"\n  generación de {DOCUMENTS} archivos: {generation:.1f} s"
        f"\n  ingesta completa: {full_s:.1f} s ({full_s / DOCUMENTS * 1000:.0f} ms/doc)"
        f"\n  incremental sin cambios: {incremental_s:.1f} s"
        f"\n  impacto p95: {_p95(impact_ms):.1f} ms · subgrafo p95: {_p95(graph_ms):.1f} ms"
    )
    assert full_s < FULL_LIMIT_S
    assert incremental_s < INCREMENTAL_LIMIT_S
    assert _p95(impact_ms) < QUERY_P95_LIMIT_MS
    assert _p95(graph_ms) < QUERY_P95_LIMIT_MS
