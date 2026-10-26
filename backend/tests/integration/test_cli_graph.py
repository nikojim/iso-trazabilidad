import csv
import io
import json
from pathlib import Path

import networkx as nx
import pytest
from typer.testing import CliRunner

from app.cli import app
from tests.fixtures.builders import build_pdf, heading, ref

runner = CliRunner()


def write_pdf(path: Path, refs: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    build_pdf(path, [[heading("4 REFERENCIAS"), *(ref(c) for c in refs), heading("5 HISTORIAL")]])


@pytest.fixture
def env(tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Norma A: B <- A <- C, como en el SKILL. Norma B: otro manual que cita a ES de A."""
    docs = tmp_path / "documents"
    write_pdf(docs / "A" / "ES-SGC-001-01 Calidad.pdf", [])
    write_pdf(docs / "A" / "MC-SGG-435-23 Manual.pdf", ["ES-SGC-001"])
    write_pdf(docs / "A" / "sub" / "PR-SGG-101-02 Personal.pdf", ["MC-SGG-435"])
    write_pdf(docs / "B" / "MC-SGG-435-23 Manual.pdf", ["ES-SGC-001"])
    monkeypatch.setenv("ISO_DATABASE_URL", db_url)
    monkeypatch.setenv("ISO_DOCUMENTS_DIR", str(docs))
    assert runner.invoke(app, ["db", "init"]).exit_code == 0
    assert runner.invoke(app, ["ingest"]).exit_code == 0
    return tmp_path


def invoke(*args: str) -> str:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def test_graph_list(env: Path) -> None:
    lines = invoke("graph", "list").splitlines()

    assert lines[0].startswith("A ") and "documentos    3" in lines[0]
    assert lines[1].startswith("B ") and "a otra norma    1" in lines[1]
    assert lines[2].startswith("Total") and "documentos    4" in lines[2]


def test_impact_crosses_normas(env: Path) -> None:
    output = invoke("impact", "ES-SGC-001", "--depth", "2")

    assert "Cambio en A/ES-SGC-001" in output
    assert "Posibles documentos a revisar" in output
    assert "Directos: 2 · indirectos: 1" in output
    assert "PR-SGG-101 → MC-SGG-435 → ES-SGC-001" in output


def test_impact_json(env: Path) -> None:
    payload = json.loads(invoke("impact", "ES-SGC-001", "--format", "json"))

    assert (payload["root_norma"], payload["root_code"]) == ("A", "ES-SGC-001")
    assert [(i["norma"], i["code"]) for i in payload["direct"]] == [
        ("A", "MC-SGG-435"),
        ("B", "MC-SGG-435"),
    ]
    assert [i["code"] for i in payload["indirect"]] == ["PR-SGG-101"]
    assert payload["summary"]["by_depth"] == {"1": 2, "2": 1}


def test_impact_csv_file(env: Path) -> None:
    target = env / "impacto.csv"

    invoke("impact", "ES-SGC-001", "--format", "csv", "--output", str(target))

    text = target.read_text("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    assert [(row[4], row[5]) for row in rows[2:]] == [
        ("A", "MC-SGG-435"),
        ("B", "MC-SGG-435"),
        ("A", "PR-SGG-101"),
    ]


def test_impact_requires_norma_when_code_is_in_several(env: Path) -> None:
    result = runner.invoke(app, ["impact", "MC-SGG-435"])

    assert result.exit_code == 2
    assert "varias normas (A, B)" in result.output
    assert "Cambio en B/MC-SGG-435" in invoke("impact", "MC-SGG-435", "--norma", "B")


def test_impact_infers_the_only_norma(env: Path) -> None:
    # PR-SGG-101 solo existe en A: no hace falta --norma.
    output = invoke("impact", "PR-SGG-101")

    assert "Cambio en A/PR-SGG-101" in output
    assert "Directos: 0" in output


def test_impact_errors(env: Path) -> None:
    assert runner.invoke(app, ["impact", "XX-ABC-999"]).exit_code == 2
    unknown = runner.invoke(app, ["impact", "MC-SGG-435", "-n", "Z"])
    assert unknown.exit_code == 2 and "Normas: A, B" in unknown.output
    too_deep = runner.invoke(app, ["impact", "MC-SGG-435", "-n", "A", "--depth", "99"])
    assert too_deep.exit_code == 2
    assert "profundidad" in too_deep.output


def test_graph_export_single_file(env: Path) -> None:
    target = env / "export" / "todo.graphml"

    invoke("graph", "export", "--format", "graphml", "--output", str(target))

    graph = nx.read_graphml(target)
    assert set(graph.edges) == {
        ("A/MC-SGG-435", "A/ES-SGC-001"),
        ("A/PR-SGG-101", "A/MC-SGG-435"),
        ("B/MC-SGG-435", "A/ES-SGC-001"),
    }
    assert graph.nodes["B/MC-SGG-435"]["norma"] == "B"
    assert graph.edges["B/MC-SGG-435", "A/ES-SGC-001"]["cross_norma"] is True


def test_graph_export_json(env: Path) -> None:
    target = env / "grafo.json"

    invoke("graph", "export", "--format", "json", "--output", str(target))

    payload = json.loads(target.read_text("utf-8"))
    assert payload["graph"]["name"] == "iso-trace"
    assert len(payload["nodes"]) == 4


def test_validate_reports_the_whole_graph(env: Path) -> None:
    output = invoke("validate", "--no-hashes")

    assert "Referencias pendientes: 0 códigos" in output


def test_api_openapi_export(env: Path) -> None:
    target = env / "openapi.json"

    invoke("api", "openapi", "--output", str(target))

    assert "/api/documents/{code}/impact" in json.loads(target.read_text("utf-8"))["paths"]
