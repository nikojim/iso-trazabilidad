"""Grafo de trazabilidad único (todas las normas) con NetworkX, construido desde SQLite.

Semántica (CLAUDE.md, regla 3): una arista ``A -> B`` significa **A cita a B**.
- Salientes de A (lo que A usa): ``successors(A)``.
- Entrantes de B (lo que depende de B): ``predecessors(B)``.

La carpeta raíz de cada documento es su **norma**. El código es único dentro de la norma,
así que la clave de un nodo documento es ``"norma/código"`` (``node_key``); los códigos
citados que todavía no tienen documento (o que son ambiguos entre normas) son nodos
virtuales con el código como clave (``resolved=False``). Las aristas entre normas distintas
llevan ``cross_norma=True``. SQLite es la fuente de verdad: el grafo es efímero y se cachea
por ``graph_version``.
"""

import itertools
import json
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import networkx as nx
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.db.meta import get_graph_version
from app.ingestion.codes import split_code
from app.models import Document, DocumentReference

Direction = Literal["in", "out", "both"]
GRAPH_NAME = "iso-trace"


class DocumentNotInGraphError(LookupError):
    """El código no es un documento ni un código citado en el grafo."""


@dataclass(frozen=True, slots=True)
class GraphFilters:
    groups: frozenset[str] | None = None  # tipos de relación (general, procedimientos…)
    include_unresolved: bool = True
    include_inactive: bool = False


DEFAULT_FILTERS = GraphFilters()


@dataclass(frozen=True, slots=True)
class NormaSummary:
    name: str
    documents: int
    references: int  # referencias que salen de documentos de la norma
    unresolved: int
    cross_norma: int  # referencias resueltas hacia documentos de otra norma


@dataclass(slots=True)
class Neighborhood:
    graph: nx.DiGraph
    distances: dict[str, int]
    truncated: bool


def node_key(norma: str, code: str) -> str:
    """Clave del nodo de un documento; las normas son carpetas y no contienen ``/``."""
    return f"{norma}/{code}"


# ----------------------------------------------------------------------------- normas


def list_normas(session: Session) -> list[NormaSummary]:
    documents = dict(
        session.execute(
            select(Document.norma, func.count())
            .where(Document.is_active.is_(True))
            .group_by(Document.norma)
        ).all()
    )
    source, target = aliased(Document), aliased(Document)
    reference_rows = session.execute(
        select(
            source.norma,
            func.count(),
            func.count().filter(DocumentReference.target_document_id.is_(None)),
            func.count().filter(target.norma != source.norma),
        )
        .join(source, DocumentReference.source_document_id == source.id)
        .outerjoin(target, DocumentReference.target_document_id == target.id)
        .where(source.is_active.is_(True))
        .group_by(source.norma)
    ).all()
    references = {name: tuple(counts) for name, *counts in reference_rows}
    return [
        NormaSummary(name, count, *references.get(name, (0, 0, 0)))
        for name, count in sorted(documents.items())
        if name  # "" agrupa archivos sueltos de versiones anteriores: no es una norma
    ]


def norma_names(session: Session) -> list[str]:
    return [summary.name for summary in list_normas(session)]


# ----------------------------------------------------------------------------- construcción


def build_graph(session: Session, filters: GraphFilters = DEFAULT_FILTERS) -> nx.DiGraph:
    graph = nx.DiGraph(name=GRAPH_NAME)

    query = select(Document).where(Document.norma != "")
    if not filters.include_inactive:
        query = query.where(Document.is_active.is_(True))
    documents = {doc.id: doc for doc in session.scalars(query)}
    for doc in documents.values():
        graph.add_node(node_key(doc.norma, doc.code), **_document_attrs(doc))

    references = session.scalars(
        select(DocumentReference)
        .where(DocumentReference.source_document_id.in_(documents))
        .order_by(DocumentReference.id)
    )
    for reference in references:
        if filters.groups is not None and reference.group_name not in filters.groups:
            continue
        source_doc = documents[reference.source_document_id]
        target_doc = documents.get(reference.target_document_id or -1)
        if target_doc is None:
            if not filters.include_unresolved:
                continue
            target = reference.target_code
            if target not in graph:
                graph.add_node(target, **_virtual_attrs(target, reference.target_title_hint))
        else:
            target = node_key(target_doc.norma, target_doc.code)
        graph.add_edge(
            node_key(source_doc.norma, source_doc.code),
            target,
            group=reference.group_name,
            occurrences=reference.occurrence_count,
            mixed_groups=reference.has_mixed_groups,
            title_hint=reference.target_title_hint,
            cross_norma=target_doc is not None and target_doc.norma != source_doc.norma,
        )
    return graph


def _document_attrs(doc: Document) -> dict[str, Any]:
    return {
        "code": doc.code,
        "norma": doc.norma,
        "title": doc.title,
        "document_type": doc.document_type,
        "system_code": doc.system_code,
        "version": doc.version,
        "status": doc.extraction_status.value,
        "file_format": doc.file_format.value,
        "folder": doc.folder,
        "document_id": doc.id,
        "active": doc.is_active,
        "resolved": True,
    }


def _virtual_attrs(code: str, title_hint: str | None) -> dict[str, Any]:
    document_type, system_code = split_code(code)
    return {
        "code": code,
        "norma": None,
        "title": title_hint,
        "document_type": document_type,
        "system_code": system_code,
        "version": None,
        "status": None,
        "file_format": None,
        "folder": None,
        "document_id": None,
        "active": False,
        "resolved": False,
    }


class GraphCache:
    """Grafo en memoria (uno por combinación de filtros), reconstruido al cambiar
    ``meta.graph_version``."""

    def __init__(self) -> None:
        self._items: dict[GraphFilters, tuple[int, nx.DiGraph]] = {}

    def get(self, session: Session, filters: GraphFilters = DEFAULT_FILTERS) -> nx.DiGraph:
        version = get_graph_version(session)
        cached = self._items.get(filters)
        if cached is not None and cached[0] == version:
            return cached[1]
        graph = build_graph(session, filters)
        self._items[filters] = (version, graph)
        return graph


# ----------------------------------------------------------------------------- consultas


def require_node(graph: nx.DiGraph, key: str) -> str:
    """El nodo con esa clave (``norma/código`` o el código de un citado sin documento)."""
    key = key.strip()
    for candidate in (key, key.upper()):
        if candidate in graph:
            return candidate
    raise DocumentNotInGraphError(f"{key} no está en el grafo")


def bfs(
    graph: nx.DiGraph,
    root: str,
    depth: int,
    neighbors: Callable[[str], Iterable[str]],
) -> dict[str, tuple[int, str]]:
    """Distancia mínima y padre BFS de cada nodo alcanzable hasta ``depth``.

    El conjunto de visitados protege contra ciclos; la raíz nunca aparece en el resultado.
    """
    found: dict[str, tuple[int, str]] = {}
    visited = {root}
    queue = deque([(root, 0)])
    while queue:
        node, distance = queue.popleft()
        if distance == depth:
            continue
        for neighbor in sorted(neighbors(node)):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            found[neighbor] = (distance + 1, node)
            queue.append((neighbor, distance + 1))
    return found


def neighbors_for(graph: nx.DiGraph, direction: Direction) -> Callable[[str], Iterable[str]]:
    if direction == "in":
        return graph.predecessors
    if direction == "out":
        return graph.successors
    return lambda node: itertools.chain(graph.predecessors(node), graph.successors(node))


def neighborhood(
    graph: nx.DiGraph, key: str, depth: int, direction: Direction, max_nodes: int
) -> Neighborhood:
    """Subgrafo alrededor de ``key`` (para la UI), recortado por distancia a ``max_nodes``."""
    root = require_node(graph, key)
    reached = bfs(graph, root, depth, neighbors_for(graph, direction))
    distances = {root: 0, **{node: dist for node, (dist, _) in reached.items()}}
    ordered = sorted(distances, key=lambda node: (distances[node], node))
    truncated = len(ordered) > max_nodes
    kept = ordered[:max_nodes]
    return Neighborhood(
        graph=graph.subgraph(kept).copy(),
        distances={node: distances[node] for node in kept},
        truncated=truncated,
    )


def find_cycles(graph: nx.DiGraph, *, length_bound: int = 10, limit: int = 100) -> list[list[str]]:
    """Ciclos simples (cada uno empieza en su menor nodo), acotados en longitud y cantidad."""
    cycles = itertools.islice(nx.simple_cycles(graph, length_bound=length_bound), limit)
    normalized = []
    for cycle in cycles:
        start = cycle.index(min(cycle))
        normalized.append(cycle[start:] + cycle[:start])
    return sorted(normalized, key=lambda c: (len(c), c))


def isolated_documents(graph: nx.DiGraph) -> list[str]:
    return sorted(
        node
        for node, data in graph.nodes(data=True)
        if data["resolved"] and data["active"] and graph.degree(node) == 0
    )


# ----------------------------------------------------------------------------- exportación


def export_graphml(graph: nx.DiGraph, path: Path) -> None:
    """GraphML admite solo atributos escalares: ``None`` se exporta como cadena vacía."""
    clean = nx.DiGraph(name=graph.graph.get("name", ""))
    for node, data in graph.nodes(data=True):
        clean.add_node(node, **{k: "" if v is None else v for k, v in data.items()})
    for source, target, data in graph.edges(data=True):
        clean.add_edge(source, target, **{k: "" if v is None else v for k, v in data.items()})
    nx.write_graphml(clean, path, encoding="utf-8")


def graph_to_json(graph: nx.DiGraph) -> dict[str, Any]:
    return nx.node_link_data(graph, edges="edges")


def export_json(graph: nx.DiGraph, path: Path) -> None:
    path.write_text(json.dumps(graph_to_json(graph), ensure_ascii=False, indent=2), "utf-8")
