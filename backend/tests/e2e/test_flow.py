"""Flujo completo: documentos sintéticos → CLI (db init, ingest) → API de consulta.

Un solo grafo con dos normas (carpetas raíz):
- ``Calidad``: réplica del manual MC-SGG-435 (PDF), un procedimiento en Word que cita al
  manual, un estándar con la sección vacía, un listado sin sección REFERENCIAS y una
  planilla XLSX (se puede citar; no se analizan sus referencias).
- ``Servicios``: una política que cita al manual, al estándar y a la planilla de Calidad.

Se verifica que lo que se consulta por la API coincide con lo ingerido por la CLI, que las
referencias cruzan normas, que cada corrida deja su log y que una reingesta incremental
actualiza la API sin reiniciarla.
"""

import csv
import io
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from app.api.main import create_app
from app.cli import app as cli
from app.config import Settings
from tests.fixtures.builders import (
    ACCEPTANCE_GENERAL,
    ACCEPTANCE_PROCEDURES,
    MANUAL_HEADER,
    Heading,
    Line,
    Para,
    build_docx,
    build_pdf,
    build_xlsx,
    heading,
    manual_pages,
    ref,
)

runner = CliRunner()
ACCEPTANCE_CODES = set(ACCEPTANCE_GENERAL) | set(ACCEPTANCE_PROCEDURES)


def write_pdf(path: Path, pages: list[list[Line]], **kwargs: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    build_pdf(path, pages, **kwargs)  # type: ignore[arg-type]


def write_procedure(path: Path, cited: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    build_docx(
        path,
        [
            Para("Referencia/Versión : PR-SGG-101/02"),
            Heading("OBJETIVO"),
            Para("Gestionar el personal."),
            Heading("REFERENCIAS"),
            *(Para(f"[{code}]\tDocumento citado") for code in cited),
            Heading("HISTORIAL"),
            Para("02 Versión inicial"),
        ],
    )


def cli_ok(*args: str) -> str:
    result = runner.invoke(cli, list(args))
    assert result.exit_code == 0, result.output
    return result.output


@pytest.fixture
def docs(tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "documents"
    write_pdf(root / "Calidad" / "MC-SGG-435-23 Manual.pdf", manual_pages(), header=MANUAL_HEADER)
    write_pdf(
        root / "Calidad" / "ES-SGC-001-01 Calidad.pdf",
        [[heading("4 REFERENCIAS"), heading("5 HISTORIAL"), Line("01 Versión inicial")]],
    )
    write_pdf(
        root / "Calidad" / "Listados" / "LC-SGC-500-01 Listado.pdf",
        [[heading("1 HISTORIAL"), heading("2 LISTADO"), Line("PO-SGS-400 Política")]],
    )
    write_procedure(
        root / "Calidad" / "Procedimientos" / "PR-SGG-101-02 Personal.docx", ["MC-SGG-435"]
    )
    build_xlsx(root / "Calidad" / "Registros" / "RG-SGC-010-01 Registro.xlsx")
    (root / "Calidad" / "notas.pptx").write_bytes(b"no soportado")
    write_pdf(
        root / "Servicios" / "PO-SGS-615-01 Politica.pdf",
        [
            [
                heading("4 REFERENCIAS"),
                ref("MC-SGG-435"),
                ref("ES-SGC-001"),
                ref("RG-SGC-010"),
                heading("5 HISTORIAL"),
            ]
        ],
    )
    write_pdf(root / "suelto.pdf", [[heading("4 REFERENCIAS"), heading("5 HISTORIAL")]])

    monkeypatch.setenv("ISO_DATABASE_URL", db_url)
    monkeypatch.setenv("ISO_DOCUMENTS_DIR", str(root))
    monkeypatch.setenv("ISO_LOG_DIR", str(tmp_path / "logs"))
    cli_ok("db", "init")
    return root


@pytest.fixture
def api(docs: Path, db_url: str) -> Iterator[TestClient]:
    output = cli_ok("ingest")
    assert "nuevos 6" in output
    assert "formatos no soportados 1" in output
    assert "suelto.pdf" in output  # informado y no procesado
    assert "Log de la corrida:" in output

    settings = Settings(_env_file=None, database_url=db_url, documents_dir=docs)
    with TestClient(create_app(settings)) as client:
        yield client


def get(client: TestClient, url: str, status: int = 200, **params: object) -> dict:
    response = client.get(url, params=params)
    assert response.status_code == status, response.text
    return response.json()


def test_normas_come_from_root_folders(api: TestClient) -> None:
    normas = {n["name"]: n for n in get(api, "/api/normas")}

    assert set(normas) == {"Calidad", "Servicios"}
    assert normas["Calidad"]["documents"] == 5
    # La política de Servicios cita tres documentos de Calidad: todos resueltos.
    assert (normas["Servicios"]["unresolved"], normas["Servicios"]["cross_norma"]) == (0, 3)


def test_run_log_is_written(api: TestClient, tmp_path: Path) -> None:
    (log,) = (tmp_path / "logs").iterdir()
    text = log.read_text("utf-8")

    assert log.name.startswith("ingest-00001-")
    assert "inicio corrida=1 modo=full" in text
    assert "archivo_sin_norma ruta=suelto.pdf" in text
    assert 'documento ruta="Calidad/MC-SGG-435-23 Manual.pdf"' in text
    assert "referencia_duplicada" in text and "destino=PR-SGG-101 veces=2" in text
    assert "formato=xlsx accion=created estado=not_applicable" in text
    assert "re_resolucion" in text  # lo que citaba Servicios se resolvió al llegar Calidad
    assert "resumen corrida=1 estado=completed" in text and "nuevos=6" in text


def test_manual_acceptance_case_through_the_api(api: TestClient) -> None:
    detail = get(api, "/api/documents/MC-SGG-435")
    refs = get(api, "/api/documents/MC-SGG-435/references")

    assert (detail["norma"], detail["extraction_status"], detail["version"]) == (
        "Calidad",
        "ok",
        "23",
    )
    every = refs["outgoing"] + refs["unresolved"]
    assert {r["code"] for r in every} == ACCEPTANCE_CODES  # 35 relaciones
    assert sum(r["occurrence_count"] for r in every) == 36
    assert sum(r["group"] == "procedimientos" for r in every) == 8
    assert {(r["norma"], r["code"]) for r in refs["outgoing"]} == {
        ("Calidad", "ES-SGC-001"),
        ("Calidad", "LC-SGC-500"),
        ("Calidad", "PR-SGG-101"),
        ("Servicios", "PO-SGS-615"),  # referencia entre normas
    }
    pr = next(r for r in refs["outgoing"] if r["code"] == "PR-SGG-101")
    assert (pr["group"], pr["occurrence_count"]) == ("procedimientos", 2)
    # Nada fuera de REFERENCIAS: ni §3, ni HISTORIAL, ni DEFINICIONES, ni DESCRIPCIÓN.
    assert "AC-AFP-698" not in {r["code"] for r in every}
    assert [(r["norma"], r["code"], r["cross_norma"]) for r in refs["incoming"]] == [
        ("Calidad", "PR-SGG-101", False),
        ("Servicios", "PO-SGS-615", True),
    ]


def test_document_states(api: TestClient) -> None:
    standard = get(api, "/api/documents/ES-SGC-001")
    listing = get(api, "/api/documents/LC-SGC-500")
    procedure = get(api, "/api/documents/PR-SGG-101")
    sheet = get(api, "/api/documents/RG-SGC-010")

    assert standard["extraction_status"] == "no_references"
    assert listing["extraction_status"] == "no_section"
    assert listing["open_issues"] == []  # sin sección: se registra en silencio
    assert (procedure["file_format"], procedure["outgoing_count"]) == ("docx", 1)
    assert (sheet["file_format"], sheet["extraction_status"]) == ("xlsx", "not_applicable")
    assert sheet["incoming_count"] == 1


def test_impact_crosses_normas(api: TestClient) -> None:
    impact = get(api, "/api/documents/ES-SGC-001/impact", depth=3)

    assert [(i["norma"], i["code"]) for i in impact["direct"]] == [
        ("Calidad", "MC-SGG-435"),
        ("Servicios", "PO-SGS-615"),
    ]
    assert [(i["code"], i["path"]) for i in impact["indirect"]] == [
        ("PR-SGG-101", ["PR-SGG-101", "MC-SGG-435", "ES-SGC-001"])
    ]
    assert "Posibles documentos a revisar" in impact["disclaimer"]


def test_dependencies_of_a_document_to_modify(api: TestClient) -> None:
    deps = get(api, "/api/documents/PO-SGS-615/dependencies", depth=1)

    assert [(i["node_id"], i["relation"]) for i in deps["direct"]] == [
        ("Calidad/ES-SGC-001", "directo"),
        ("Calidad/MC-SGG-435", "directo"),
        ("Calidad/RG-SGC-010", "directo"),
    ]
    full = get(api, "/api/graph/full")
    assert {i["node_id"] for i in deps["direct"]} <= {n["id"] for n in full["nodes"]}


def test_cli_and_api_export_the_same_impact(api: TestClient, tmp_path: Path) -> None:
    target = tmp_path / "impacto.csv"
    cli_ok("impact", "ES-SGC-001", "--depth", "3", "--format", "csv", "-o", str(target))
    response = api.get("/api/documents/ES-SGC-001/impact.csv", params={"depth": 3})

    def rows(text: str) -> list[list[str]]:
        parsed = list(csv.reader(io.StringIO(text.lstrip("\ufeff")), delimiter=";"))
        return [row[:2] + row[3:] for row in parsed[2:]]  # sin la fecha de generación

    assert response.status_code == 200
    assert rows(response.text) == rows(target.read_text("utf-8"))
    assert [row[4] for row in rows(response.text)] == ["MC-SGG-435", "PO-SGS-615", "PR-SGG-101"]


def test_neighborhood_and_quality(api: TestClient) -> None:
    hood = get(api, "/api/graph", code="ES-SGC-001", direction="in", depth=2)
    issues = get(api, "/api/quality/issues", norma="Calidad")

    edges = {(e["source"], e["target"]) for e in hood["edges"]}
    assert {n["code"] for n in hood["nodes"]} == {
        "ES-SGC-001",
        "MC-SGG-435",
        "PR-SGG-101",
        "PO-SGS-615",
    }
    # Se muestran todas las aristas entre los nodos del subgrafo, también MC → PR.
    assert edges == {
        ("Calidad/MC-SGG-435", "Calidad/ES-SGC-001"),
        ("Calidad/PR-SGG-101", "Calidad/MC-SGG-435"),
        ("Calidad/MC-SGG-435", "Calidad/PR-SGG-101"),
        ("Servicios/PO-SGS-615", "Calidad/ES-SGC-001"),
        ("Servicios/PO-SGS-615", "Calidad/MC-SGG-435"),
        ("Calidad/MC-SGG-435", "Servicios/PO-SGS-615"),  # el manual también cita la política
    }
    assert not hood["truncated"]
    # MC cita a PR y PR cita a MC: ciclo detectado como incidencia derivada.
    assert any(i["type"] == "cycle" for i in issues["items"])


def test_incremental_reingestion_updates_the_api(api: TestClient, docs: Path) -> None:
    unchanged = cli_ok("ingest", "--incremental")
    assert "nuevos 0 · actualizados 0 · sin cambios 6" in unchanged

    # El procedimiento deja de citar al manual y pasa a citar al estándar; el listado se borra.
    write_procedure(
        docs / "Calidad" / "Procedimientos" / "PR-SGG-101-02 Personal.docx", ["ES-SGC-001"]
    )
    (docs / "Calidad" / "Listados" / "LC-SGC-500-01 Listado.pdf").unlink()
    changed = cli_ok("ingest", "--incremental")
    assert "actualizados 1" in changed and "faltantes 1" in changed

    # La misma instancia de la API ve el cambio (la caché se invalida por graph_version).
    impact = get(api, "/api/documents/ES-SGC-001/impact", depth=3)
    refs = get(api, "/api/documents/MC-SGG-435/references")
    assert sorted(i["code"] for i in impact["direct"]) == [
        "MC-SGG-435",
        "PO-SGS-615",
        "PR-SGG-101",
    ]
    assert impact["indirect"] == []
    assert [r["code"] for r in refs["incoming"]] == ["PO-SGS-615"]
    # El listado ya no existe: la cita del manual vuelve a quedar pendiente.
    assert "LC-SGC-500" in {r["code"] for r in refs["unresolved"]}
    assert get(api, "/api/documents", norma="Calidad")["total"] == 4
