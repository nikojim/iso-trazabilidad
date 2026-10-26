"""Análisis de impacto (predecesores) y de dependencias (sucesores) en el grafo único.

El recorrido cruza normas: una referencia entre normas es una arista más.

El resultado es siempre un conjunto de **posibles documentos a revisar**, nunca la
confirmación de que deban modificarse (CLAUDE.md, regla 10).
"""

import csv
import io
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

import networkx as nx

from app.services.graph import bfs, require_node

DISCLAIMER = "Posibles documentos a revisar. No implica necesidad confirmada de modificación."


class DepthOutOfRangeError(ValueError):
    """La profundidad pedida está fuera de 1..máximo configurado."""


@dataclass(frozen=True, slots=True)
class TraversalItem:
    code: str
    norma: str | None  # None para un código citado sin documento
    node_id: str  # clave del nodo en el grafo ("norma/código" o el código si no hay documento)
    title: str | None
    document_type: str
    depth: int
    path: tuple[str, ...]  # códigos en el sentido de las aristas: cada paso "cita a" el siguiente
    resolved: bool

    @property
    def relation(self) -> str:
        return "directo" if self.depth == 1 else "indirecto"


@dataclass(slots=True)
class TraversalResult:
    kind: Literal["impact", "dependencies"]
    root_code: str
    root_norma: str | None
    root_node_id: str
    root_title: str | None
    root_resolved: bool
    depth: int
    items: list[TraversalItem] = field(default_factory=list)
    disclaimer: str = DISCLAIMER

    @property
    def direct(self) -> list[TraversalItem]:
        return [item for item in self.items if item.depth == 1]

    @property
    def indirect(self) -> list[TraversalItem]:
        return [item for item in self.items if item.depth > 1]

    def summary(self) -> dict[str, dict[str, int]]:
        return {
            "by_depth": {
                str(k): v for k, v in sorted(Counter(i.depth for i in self.items).items())
            },
            "by_type": dict(sorted(Counter(i.document_type for i in self.items).items())),
        }


def check_depth(depth: int, max_depth: int) -> None:
    if not 1 <= depth <= max_depth:
        raise DepthOutOfRangeError(
            f"La profundidad debe estar entre 1 y {max_depth} (se pidió {depth})"
        )


def impacted_by(
    graph: nx.DiGraph,
    code: str,
    depth: int,
    *,
    max_depth: int,
    types: frozenset[str] | None = None,
) -> TraversalResult:
    """Documentos que citan al nodo ``code`` directa o transitivamente (recorrido inverso)."""
    return _traverse(graph, code, depth, max_depth, types, kind="impact")


def dependencies_of(
    graph: nx.DiGraph,
    code: str,
    depth: int,
    *,
    max_depth: int,
    types: frozenset[str] | None = None,
) -> TraversalResult:
    """Documentos que el nodo ``code`` cita directa o transitivamente."""
    return _traverse(graph, code, depth, max_depth, types, kind="dependencies")


def _traverse(
    graph: nx.DiGraph,
    code: str,
    depth: int,
    max_depth: int,
    types: frozenset[str] | None,
    kind: Literal["impact", "dependencies"],
) -> TraversalResult:
    check_depth(depth, max_depth)
    root = require_node(graph, code)
    neighbors = graph.predecessors if kind == "impact" else graph.successors
    reached = bfs(graph, root, depth, neighbors)

    items = []
    for node, (distance, _) in reached.items():
        data = graph.nodes[node]
        if types is not None and data["document_type"] not in types:
            continue  # el filtro de tipo solo oculta resultados; el recorrido pasa por todos
        chain = [node]
        while chain[-1] != root:
            chain.append(reached[chain[-1]][1])
        ordered = chain if kind == "impact" else list(reversed(chain))
        items.append(
            TraversalItem(
                code=data["code"],
                norma=data.get("norma"),
                node_id=node,
                title=data["title"],
                document_type=data["document_type"],
                depth=distance,
                path=tuple(graph.nodes[n]["code"] for n in ordered),
                resolved=data["resolved"],
            )
        )
    items.sort(key=lambda item: (item.depth, item.code, item.norma or ""))
    root_data = graph.nodes[root]
    return TraversalResult(
        kind=kind,
        root_code=root_data["code"],
        root_norma=root_data.get("norma"),
        root_node_id=root,
        root_title=root_data["title"],
        root_resolved=root_data["resolved"],
        depth=depth,
        items=items,
    )


CSV_COLUMNS = [
    "norma_modificado",
    "documento_modificado",
    "fecha",
    "profundidad_maxima",
    "norma",
    "codigo",
    "titulo",
    "tipo",
    "profundidad",
    "relacion",
    "ruta",
]


def impact_to_csv(result: TraversalResult, generated_at: datetime | None = None) -> str:
    """CSV para Excel en español: UTF-8 con BOM y separador ``;``; la primera fila es la leyenda."""
    generated = (generated_at or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M")
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow([result.disclaimer])
    writer.writerow(CSV_COLUMNS)
    for item in result.items:
        writer.writerow(
            [
                result.root_norma or "",
                result.root_code,
                generated,
                result.depth,
                item.norma or "",
                item.code,
                item.title or "",
                item.document_type,
                item.depth,
                item.relation,
                " → ".join(item.path),
            ]
        )
    return "﻿" + buffer.getvalue()
