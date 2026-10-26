"""API REST de consulta sobre un grafo único con dos normas sintéticas (A y B)."""

import csv
import io
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.api.main import create_app
from app.config import Settings
from app.ingestion.config import ExtractionConfig
from app.services.impact import DISCLAIMER
from app.services.ingest import IngestionService, IngestOptions
from tests.fixtures.builders import Line, build_pdf, build_xlsx, heading, ref


def write(path: Path, refs: list[str], procedures: list[str] = (), extra: list[Line] = ()) -> None:  # type: ignore[assignment]
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [heading("4 REFERENCIAS"), *(ref(c, f"Doc {c[-3:]}") for c in refs)]
    if procedures:
        lines += [Line("Procedimientos", bold=True), *(ref(c, "Proc") for c in procedures)]
    lines += [*extra, heading("5 HISTORIAL")]
    build_pdf(path, [lines])


@pytest.fixture
def client(tmp_path: Path, db_url: str, migrated_engine: Engine) -> Iterator[TestClient]:
    """Norma A: PR -> MC -> ES (y MC <-> PC en ciclo, PO pendiente, MC cita la planilla LC de B).
    Norma B: otro MC-SGG-435 (documento distinto) que cita a ES de A; planilla LC-SGC-500."""
    docs = tmp_path / "documents"
    write(docs / "A" / "ES-SGC-001-01 Calidad.pdf", [])
    write(
        docs / "A" / "MC-SGG-435-23 Manual.pdf",
        ["ES-SGC-001", "PO-SGS-400", "PC-SGSA-914", "LC-SGC-500"],
    )
    write(docs / "A" / "sub" / "PR-SGG-101-02 Personal.pdf", [], procedures=["MC-SGG-435"])
    write(docs / "A" / "PC-SGSA-914-02 Plan.pdf", ["MC-SGG-435"])
    write(docs / "A" / "AL-SGS-401-01 Alcance.pdf", [], extra=[Line("[ES-SG-1] mal")])
    write(docs / "B" / "MC-SGG-435-23 Manual.pdf", ["ES-SGC-001"])
    build_xlsx(docs / "B" / "LC-SGC-500-01 Listado.xlsx")
    IngestionService(migrated_engine, docs, ExtractionConfig()).ingest_path(docs, IngestOptions())

    settings = Settings(
        _env_file=None,
        database_url=db_url,
        documents_dir=docs,
        max_depth=5,
        graph_max_nodes=50,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def get(client: TestClient, url: str, status: int = 200, **params: object) -> dict:
    response = client.get(url, params=params)
    assert response.status_code == status, response.text
    return response.json()


# ----------------------------------------------------------------------------- general


def test_health_and_normas(client: TestClient) -> None:
    health = get(client, "/api/health")
    normas = get(client, "/api/normas")

    assert health["status"] == "ok"
    assert health["schema_revision"] == "0003"
    assert health["limits"] == {
        "default_depth": 2,
        "max_depth": 5,
        "graph_max_nodes": 50,
        "graph_full_max_nodes": 3000,
    }
    assert {n["name"]: (n["documents"], n["cross_norma"]) for n in normas} == {
        "A": (5, 1),
        "B": (2, 1),
    }


def test_stats(client: TestClient) -> None:
    stats = get(client, "/api/stats")

    assert stats["documents"] == 7
    assert {n["name"] for n in stats["normas"]} == {"A", "B"}


def test_cors_only_for_frontend_origin(client: TestClient) -> None:
    allowed = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    other = client.get("/api/health", headers={"Origin": "http://otro.example"})

    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-origin" not in other.headers


def test_unknown_route_uses_error_format(client: TestClient) -> None:
    body = get(client, "/api/nada", status=404)

    assert body["error"]["code"] == "not_found"


# ----------------------------------------------------------------------------- documentos


def test_search_is_organized_by_norma_and_name(client: TestClient) -> None:
    everything = get(client, "/api/documents")
    first = get(client, "/api/documents", page_size=2)
    second = get(client, "/api/documents", page_size=2, page=2)
    only_b = get(client, "/api/documents", norma="B")
    by_text = get(client, "/api/documents", query="manual")
    by_type = get(client, "/api/documents", type="pr")

    assert [(i["norma"], i["title"]) for i in everything["items"]] == [
        ("A", "Alcance"),
        ("A", "Calidad"),
        ("A", "Manual"),
        ("A", "Personal"),
        ("A", "Plan"),
        ("B", "Listado"),
        ("B", "Manual"),
    ]
    assert first["total"] == 7 and len(first["items"]) == 2
    assert {i["code"] for i in first["items"]}.isdisjoint(i["code"] for i in second["items"])
    assert [(i["code"], i["file_format"]) for i in only_b["items"]] == [
        ("LC-SGC-500", "xlsx"),
        ("MC-SGG-435", "pdf"),
    ]
    assert {(i["norma"], i["code"]) for i in by_text["items"]} == {
        ("A", "MC-SGG-435"),
        ("B", "MC-SGG-435"),
    }
    assert [i["code"] for i in by_type["items"]] == ["PR-SGG-101"]


def test_search_counts(client: TestClient) -> None:
    items = get(client, "/api/documents", norma="A", query="MC-SGG")["items"]

    assert (items[0]["outgoing_count"], items[0]["incoming_count"]) == (4, 2)


def test_page_size_is_capped(client: TestClient) -> None:
    body = get(client, "/api/documents", status=422, page_size=500)

    assert body["error"]["code"] == "validation_error"


def test_detail(client: TestClient) -> None:
    detail = get(client, "/api/documents/mc-sgg-435", norma="A")

    assert detail["code"] == "MC-SGG-435"
    assert detail["norma"] == "A"
    assert detail["file_path"] == "A/MC-SGG-435-23 Manual.pdf"
    assert detail["unresolved_count"] == 1
    assert detail["references_stale"] is False
    assert detail["metadata"]["section"]["terminator"] == "historial"


def test_spreadsheet_detail(client: TestClient) -> None:
    detail = get(client, "/api/documents/LC-SGC-500")

    assert (detail["norma"], detail["file_format"]) == ("B", "xlsx")
    assert detail["extraction_status"] == "not_applicable"
    assert (detail["outgoing_count"], detail["incoming_count"]) == (0, 1)


def test_detail_requires_norma_when_code_is_in_several(client: TestClient) -> None:
    body = get(client, "/api/documents/MC-SGG-435", status=409)

    assert body["error"]["code"] == "norma_required"
    assert body["error"]["details"]["normas"] == ["A", "B"]


def test_detail_infers_the_only_norma(client: TestClient) -> None:
    assert get(client, "/api/documents/PR-SGG-101")["norma"] == "A"


def test_detail_not_found(client: TestClient) -> None:
    assert (
        get(client, "/api/documents/XX-ABC-999", status=404)["error"]["code"]
        == "document_not_found"
    )
    assert (
        get(client, "/api/documents/MC-SGG-435", status=404, norma="Z")["error"]["code"]
        == "norma_not_found"
    )
    # Solo citado, sin documento: no hay detalle (pero sí referencias e impacto).
    assert (
        get(client, "/api/documents/PO-SGS-400", status=404)["error"]["code"]
        == "document_not_found"
    )
    assert (
        get(client, "/api/documents/ES-SGC-001", status=404, norma="B")["error"]["code"]
        == "document_not_found"
    )


def test_detail_includes_open_issues(client: TestClient) -> None:
    detail = get(client, "/api/documents/AL-SGS-401")

    assert [i["type"] for i in detail["open_issues"]] == ["invalid_reference_candidate"]


def test_references(client: TestClient) -> None:
    body = get(client, "/api/documents/MC-SGG-435/references", norma="A")

    assert [(r["code"], r["norma"], r["cross_norma"]) for r in body["outgoing"]] == [
        ("ES-SGC-001", "A", False),
        ("LC-SGC-500", "B", True),
        ("PC-SGSA-914", "A", False),
    ]
    assert [(r["code"], r["resolved"]) for r in body["unresolved"]] == [("PO-SGS-400", False)]
    assert {(r["code"], r["group"]) for r in body["incoming"]} == {
        ("PC-SGSA-914", "general"),
        ("PR-SGG-101", "procedimientos"),
    }
    evidence = body["outgoing"][0]["occurrences"][0]
    assert evidence["page_number"] == 1
    assert evidence["evidence_excerpt"].startswith("[ES-SGC-001]")


def test_references_of_a_cited_code_without_document(client: TestClient) -> None:
    body = get(client, "/api/documents/PO-SGS-400/references")

    assert body["resolved"] is False and body["norma"] is None
    assert body["outgoing"] == []
    assert [(r["code"], r["norma"]) for r in body["incoming"]] == [("MC-SGG-435", "A")]


def test_references_cross_normas(client: TestClient) -> None:
    body = get(client, "/api/documents/ES-SGC-001/references")

    assert body["norma"] == "A"
    assert [(r["norma"], r["code"], r["cross_norma"]) for r in body["incoming"]] == [
        ("A", "MC-SGG-435", False),
        ("B", "MC-SGG-435", True),
    ]


# ----------------------------------------------------------------------------- impacto


def test_impact_crosses_normas(client: TestClient) -> None:
    body = get(client, "/api/documents/ES-SGC-001/impact", depth=2)

    assert body["disclaimer"] == DISCLAIMER
    assert body["root"] == {
        "code": "ES-SGC-001",
        "norma": "A",
        "node_id": "A/ES-SGC-001",
        "title": "Calidad",
        "resolved": True,
    }
    assert [(i["norma"], i["code"], i["node_id"]) for i in body["direct"]] == [
        ("A", "MC-SGG-435", "A/MC-SGG-435"),
        ("B", "MC-SGG-435", "B/MC-SGG-435"),
    ]
    assert {(i["code"], tuple(i["path"])) for i in body["indirect"]} == {
        ("PC-SGSA-914", ("PC-SGSA-914", "MC-SGG-435", "ES-SGC-001")),
        ("PR-SGG-101", ("PR-SGG-101", "MC-SGG-435", "ES-SGC-001")),
    }
    assert body["summary"]["by_depth"] == {"1": 2, "2": 2}


def test_impact_of_a_spreadsheet(client: TestClient) -> None:
    body = get(client, "/api/documents/LC-SGC-500/impact", depth=1)

    assert [i["node_id"] for i in body["direct"]] == ["A/MC-SGG-435"]


def test_impact_filters(client: TestClient) -> None:
    only_pr = get(client, "/api/documents/ES-SGC-001/impact", depth=2, types=["PR"])
    general_only = get(client, "/api/documents/ES-SGC-001/impact", depth=2, groups=["general"])

    assert [i["code"] for i in only_pr["indirect"]] == ["PR-SGG-101"]
    assert "PR-SGG-101" not in {i["code"] for i in general_only["indirect"]}


def test_impact_depth_out_of_range(client: TestClient) -> None:
    for depth in (0, 6):
        body = get(client, "/api/documents/ES-SGC-001/impact", status=400, depth=depth)
        assert body["error"]["code"] == "depth_out_of_range"


def test_impact_csv(client: TestClient) -> None:
    response = client.get("/api/documents/ES-SGC-001/impact.csv", params={"depth": 2})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "impacto-ES-SGC-001.csv" in response.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
    assert [(r[4], r[5]) for r in rows[2:]] == [
        ("A", "MC-SGG-435"),
        ("B", "MC-SGG-435"),
        ("A", "PC-SGSA-914"),
        ("A", "PR-SGG-101"),
    ]


def test_dependencies(client: TestClient) -> None:
    body = get(client, "/api/documents/PR-SGG-101/dependencies", depth=2)

    assert [i["code"] for i in body["direct"]] == ["MC-SGG-435"]
    assert {(i["code"], i["norma"]) for i in body["indirect"]} == {
        ("ES-SGC-001", "A"),
        ("LC-SGC-500", "B"),
        ("PO-SGS-400", None),
        ("PC-SGSA-914", "A"),
    }


# ----------------------------------------------------------------------------- grafo


def test_graph_neighborhood_for_cytoscape(client: TestClient) -> None:
    body = get(client, "/api/graph", code="MC-SGG-435", norma="A", depth=1)

    nodes = {n["id"]: n for n in body["nodes"]}
    assert body["root"] == "A/MC-SGG-435"
    assert nodes["A/MC-SGG-435"]["is_root"] and nodes["A/MC-SGG-435"]["distance"] == 0
    assert nodes["PO-SGS-400"]["resolved"] is False and nodes["PO-SGS-400"]["norma"] is None
    assert nodes["B/LC-SGC-500"]["file_format"] == "xlsx"
    edges = {(e["source"], e["target"]): e for e in body["edges"]}
    assert set(edges) >= {
        ("A/MC-SGG-435", "A/ES-SGC-001"),
        ("A/PR-SGG-101", "A/MC-SGG-435"),
        ("A/MC-SGG-435", "B/LC-SGC-500"),
    }
    assert edges["A/MC-SGG-435", "B/LC-SGC-500"]["cross_norma"] is True
    assert body["truncated"] is False


def test_graph_direction_types_and_truncation(client: TestClient) -> None:
    incoming = get(client, "/api/graph", code="MC-SGG-435", norma="A", direction="in")
    only_pr = get(client, "/api/graph", code="MC-SGG-435", norma="A", types=["PR"])
    capped = get(client, "/api/graph", code="MC-SGG-435", norma="A", max_nodes=2)
    resolved_only = get(
        client, "/api/graph", code="MC-SGG-435", norma="A", include_unresolved=False
    )

    assert {n["id"] for n in incoming["nodes"]} == {
        "A/MC-SGG-435",
        "A/PR-SGG-101",
        "A/PC-SGSA-914",
    }
    assert {n["id"] for n in only_pr["nodes"]} == {"A/MC-SGG-435", "A/PR-SGG-101"}
    assert capped["truncated"] and len(capped["nodes"]) == 2
    assert "PO-SGS-400" not in {n["id"] for n in resolved_only["nodes"]}


def test_graph_of_a_cited_code_without_document(client: TestClient) -> None:
    body = get(client, "/api/graph", code="PO-SGS-400", depth=1)

    assert body["root"] == "PO-SGS-400"
    assert {n["id"] for n in body["nodes"]} == {"PO-SGS-400", "A/MC-SGG-435"}


def test_graph_requires_code(client: TestClient) -> None:
    assert get(client, "/api/graph", status=422)["error"]["code"] == "validation_error"


def test_full_graph(client: TestClient) -> None:
    body = get(client, "/api/graph/full")

    assert body["normas"] == ["A", "B"]
    assert len(body["nodes"]) == 8  # 7 documentos + PO-SGS-400 citado sin documento
    assert len(body["edges"]) == 7
    assert {(e["source"], e["target"]) for e in body["edges"] if e["cross_norma"]} == {
        ("A/MC-SGG-435", "B/LC-SGC-500"),
        ("B/MC-SGG-435", "A/ES-SGC-001"),
    }
    without_pending = get(client, "/api/graph/full", include_unresolved=False)
    assert "PO-SGS-400" not in {n["id"] for n in without_pending["nodes"]}


def test_full_graph_is_capped(client: TestClient) -> None:
    settings = client.app.state.settings  # type: ignore[attr-defined]
    client.app.state.settings = settings.model_copy(update={"graph_full_max_nodes": 3})  # type: ignore[attr-defined]

    body = get(client, "/api/graph/full", status=400)

    assert body["error"]["code"] == "graph_too_large"


def test_cycles(client: TestClient) -> None:
    assert get(client, "/api/graph/cycles")["cycles"] == [["A/MC-SGG-435", "A/PC-SGSA-914"]]


# ----------------------------------------------------------------------------- calidad


def test_quality_issues_include_stored_and_derived(client: TestClient) -> None:
    body = get(client, "/api/quality/issues", norma="A", page_size=200)

    by_source = {(i["source"], i["type"]) for i in body["items"]}
    assert ("stored", "invalid_reference_candidate") in by_source
    assert ("derived", "cycle") in by_source
    assert all(i["norma"] == "A" for i in body["items"])


def test_quality_issue_filters(client: TestClient) -> None:
    stored_only = get(client, "/api/quality/issues", derived=False)
    cycles = get(client, "/api/quality/issues", type="cycle")

    assert {i["source"] for i in stored_only["items"]} == {"stored"}
    assert cycles["total"] == 1


def test_unresolved_references(client: TestClient) -> None:
    body = get(client, "/api/references/unresolved")

    assert [(i["target_code"], i["cited_by"], i["candidate_normas"]) for i in body["items"]] == [
        ("PO-SGS-400", ["A/MC-SGG-435"], [])
    ]
    # B/MC-SGG-435 cita a ES-SGC-001 de la norma A: ya no queda pendiente.
    assert get(client, "/api/references/unresolved", norma="B")["total"] == 0


def test_ingestion_runs(client: TestClient) -> None:
    body = get(client, "/api/ingestion/runs")

    assert body["total"] == 1
    run = body["items"][0]
    assert run["new_count"] == 7
    assert (run["references_count"], run["unresolved_count"]) == (7, 1)


def test_openapi_documents_every_route(client: TestClient) -> None:
    paths = get(client, "/openapi.json")["paths"]

    assert "/api/documents/{code}/impact" in paths
    assert {"/api/graph", "/api/graph/full", "/api/normas"} <= set(paths)
    assert "/api/graphs" not in paths
    assert len(paths) == 15


def test_app_refuses_uninitialized_database(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, database_url=f"sqlite:///{(tmp_path / 'x.db').as_posix()}")

    with pytest.raises(RuntimeError, match="db init"), TestClient(create_app(settings)):
        pass
