"""Recorridos, ciclos, vecindad y exportación sobre grafos construidos a mano."""

import csv
import io
import json
from pathlib import Path

import networkx as nx
import pytest

from app.services.graph import (
    DocumentNotInGraphError,
    export_graphml,
    export_json,
    find_cycles,
    isolated_documents,
    neighborhood,
)
from app.services.impact import (
    DISCLAIMER,
    DepthOutOfRangeError,
    dependencies_of,
    impact_to_csv,
    impacted_by,
)

MAX = 10


def make_graph(
    edges: list[tuple[str, str]], *, isolated: tuple[str, ...] = (), virtual: tuple[str, ...] = ()
) -> nx.DiGraph:
    """Arista (A, B) = A cita a B."""
    graph = nx.DiGraph(name="A")
    nodes = {n for edge in edges for n in edge} | set(isolated)
    for code in sorted(nodes):
        graph.add_node(
            code,
            code=code,
            title=f"Título {code}",
            document_type=code.split("-")[0],
            system_code="SGG",
            resolved=code not in virtual,
            active=code not in virtual,
        )
    for source, target in edges:
        graph.add_edge(source, target, group="general", occurrences=1, mixed_groups=False)
    return graph


def summary(result) -> list[tuple[str, int, tuple[str, ...]]]:  # type: ignore[no-untyped-def]
    return [(item.code, item.depth, item.path) for item in result.items]


def test_skill_case_6_direct_and_indirect_impact() -> None:
    # A cita a B, C cita a A: si cambia B, revisar A (directo) y C (indirecto).
    graph = make_graph([("PO-SGG-001", "ES-SGG-002"), ("PR-SGG-003", "PO-SGG-001")])

    result = impacted_by(graph, "ES-SGG-002", 2, max_depth=MAX)

    assert summary(result) == [
        ("PO-SGG-001", 1, ("PO-SGG-001", "ES-SGG-002")),
        ("PR-SGG-003", 2, ("PR-SGG-003", "PO-SGG-001", "ES-SGG-002")),
    ]
    assert [i.code for i in result.direct] == ["PO-SGG-001"]
    assert [i.code for i in result.indirect] == ["PR-SGG-003"]
    assert result.disclaimer == DISCLAIMER


def test_depth_limits_the_traversal() -> None:
    graph = make_graph([("PO-SGG-001", "ES-SGG-002"), ("PR-SGG-003", "PO-SGG-001")])

    assert [i.code for i in impacted_by(graph, "ES-SGG-002", 1, max_depth=MAX).items] == [
        "PO-SGG-001"
    ]


def test_minimum_depth_wins_when_there_are_several_paths() -> None:
    graph = make_graph(
        [("PO-SGG-001", "ES-SGG-002"), ("PR-SGG-003", "PO-SGG-001"), ("PR-SGG-003", "ES-SGG-002")]
    )

    result = impacted_by(graph, "ES-SGG-002", 3, max_depth=MAX)

    assert ("PR-SGG-003", 1, ("PR-SGG-003", "ES-SGG-002")) in summary(result)


@pytest.mark.parametrize(
    "edges",
    [
        [("PO-SGG-001", "ES-SGG-002"), ("ES-SGG-002", "PO-SGG-001")],
        [("PO-SGG-001", "ES-SGG-002"), ("ES-SGG-002", "PR-SGG-003"), ("PR-SGG-003", "PO-SGG-001")],
    ],
)
def test_cycles_terminate_and_never_include_the_root(edges: list[tuple[str, str]]) -> None:
    graph = make_graph(edges)

    result = impacted_by(graph, "ES-SGG-002", MAX, max_depth=MAX)

    codes = [i.code for i in result.items]
    assert "ES-SGG-002" not in codes
    assert len(codes) == len(set(codes)) == graph.number_of_nodes() - 1


def test_type_filter_hides_results_but_traverses_through_them() -> None:
    graph = make_graph([("PO-SGG-001", "ES-SGG-002"), ("PR-SGG-003", "PO-SGG-001")])

    result = impacted_by(graph, "ES-SGG-002", 2, max_depth=MAX, types=frozenset({"PR"}))

    assert summary(result) == [("PR-SGG-003", 2, ("PR-SGG-003", "PO-SGG-001", "ES-SGG-002"))]


def test_dependencies_follow_citations_forward() -> None:
    graph = make_graph([("PR-SGG-003", "PO-SGG-001"), ("PO-SGG-001", "ES-SGG-002")])

    result = dependencies_of(graph, "PR-SGG-003", 2, max_depth=MAX)

    assert summary(result) == [
        ("PO-SGG-001", 1, ("PR-SGG-003", "PO-SGG-001")),
        ("ES-SGG-002", 2, ("PR-SGG-003", "PO-SGG-001", "ES-SGG-002")),
    ]


def test_impact_of_a_cited_code_without_document() -> None:
    graph = make_graph([("PO-SGG-001", "ES-SGG-404")], virtual=("ES-SGG-404",))

    result = impacted_by(graph, "es-sgg-404", 1, max_depth=MAX)

    assert not result.root_resolved
    assert [i.code for i in result.items] == ["PO-SGG-001"]


@pytest.mark.parametrize("depth", [0, MAX + 1])
def test_depth_out_of_range(depth: int) -> None:
    with pytest.raises(DepthOutOfRangeError):
        impacted_by(make_graph([("PO-SGG-001", "ES-SGG-002")]), "ES-SGG-002", depth, max_depth=MAX)


def test_unknown_code() -> None:
    with pytest.raises(DocumentNotInGraphError):
        impacted_by(make_graph([("PO-SGG-001", "ES-SGG-002")]), "XX-SGG-999", 1, max_depth=MAX)


def test_find_cycles_and_isolated() -> None:
    graph = make_graph(
        [("PO-SGG-002", "ES-SGG-001"), ("ES-SGG-001", "PO-SGG-002"), ("PR-SGG-003", "ES-SGG-001")],
        isolated=("AX-SGG-009",),
    )

    assert find_cycles(graph) == [["ES-SGG-001", "PO-SGG-002"]]
    assert isolated_documents(graph) == ["AX-SGG-009"]


def test_neighborhood_by_direction_and_truncation() -> None:
    graph = make_graph(
        [("PO-SGG-001", "ES-SGG-002"), ("PR-SGG-003", "PO-SGG-001"), ("ES-SGG-002", "LC-SGG-004")]
    )

    incoming = neighborhood(graph, "ES-SGG-002", 2, "in", max_nodes=10)
    both = neighborhood(graph, "ES-SGG-002", 1, "both", max_nodes=10)
    capped = neighborhood(graph, "ES-SGG-002", 2, "both", max_nodes=2)

    assert incoming.distances == {"ES-SGG-002": 0, "PO-SGG-001": 1, "PR-SGG-003": 2}
    assert set(both.graph.nodes) == {"ES-SGG-002", "PO-SGG-001", "LC-SGG-004"}
    assert both.graph.has_edge("PO-SGG-001", "ES-SGG-002")  # el sentido se conserva
    assert capped.truncated
    assert set(capped.distances) == {"ES-SGG-002", "LC-SGG-004"}  # los más cercanos, por código


def test_graphml_round_trip_and_json(tmp_path: Path) -> None:
    graph = make_graph([("PO-SGG-001", "ES-SGG-002")])
    graph.nodes["ES-SGG-002"]["version"] = None

    export_graphml(graph, tmp_path / "A.graphml")
    export_json(graph, tmp_path / "A.json")

    reread = nx.read_graphml(tmp_path / "A.graphml")
    assert list(reread.edges) == [("PO-SGG-001", "ES-SGG-002")]
    assert reread.nodes["ES-SGG-002"]["version"] == ""
    payload = json.loads((tmp_path / "A.json").read_text("utf-8"))
    assert payload["edges"] == [
        {
            "source": "PO-SGG-001",
            "target": "ES-SGG-002",
            "group": "general",
            "occurrences": 1,
            "mixed_groups": False,
        }
    ]


def test_impact_csv_matches_json_rows() -> None:
    graph = make_graph([("PO-SGG-001", "ES-SGG-002"), ("PR-SGG-003", "PO-SGG-001")])
    result = impacted_by(graph, "ES-SGG-002", 2, max_depth=MAX)

    text = impact_to_csv(result)

    assert text.startswith("﻿")
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿")), delimiter=";"))
    assert rows[0] == [DISCLAIMER]
    assert rows[1][:2] == ["norma_modificado", "documento_modificado"]
    assert [(r[5], r[8], r[9], r[10]) for r in rows[2:]] == [
        ("PO-SGG-001", "1", "directo", "PO-SGG-001 → ES-SGG-002"),
        ("PR-SGG-003", "2", "indirecto", "PR-SGG-003 → PO-SGG-001 → ES-SGG-002"),
    ]
    assert len(rows) - 2 == len(result.items)
