"""Salud, normas, subgrafos y grafo completo para Cytoscape, ciclos y estadísticas."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from sqlalchemy import text

from app.api.deps import CacheDep, NormaQuery, SessionDep, SettingsDep
from app.api.errors import GraphTooLargeError
from app.db import migrate
from app.db.meta import get_graph_version
from app.schemas.common import ErrorResponse
from app.schemas.documents import NormaOut
from app.schemas.graph import (
    CyclesResponse,
    FullGraphResponse,
    GraphEdgeOut,
    GraphNodeOut,
    GraphResponse,
    HealthResponse,
    LimitsOut,
    NeighborhoodNodeOut,
    StatsResponse,
)
from app.services import queries
from app.services.catalog import normalize_code, resolve_node
from app.services.graph import GraphFilters, find_cycles, list_normas, neighborhood
from app.services.impact import check_depth

router = APIRouter(tags=["grafo"])
ERRORS = {
    400: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}


@router.get("/health", response_model=HealthResponse)
def health(session: SessionDep, settings: SettingsDep) -> HealthResponse:
    session.execute(text("SELECT 1"))
    return HealthResponse(
        status="ok",
        database="ok",
        schema_revision=migrate.current_revision(settings.database_url),
        graph_version=get_graph_version(session),
        limits=LimitsOut(
            default_depth=settings.default_depth,
            max_depth=settings.max_depth,
            graph_max_nodes=settings.graph_max_nodes,
            graph_full_max_nodes=settings.graph_full_max_nodes,
        ),
    )


@router.get("/normas", response_model=list[NormaOut])
def normas(session: SessionDep) -> list[NormaOut]:
    """Normas (carpetas raíz del directorio de documentos) con sus totales."""
    return [
        NormaOut(
            name=n.name,
            documents=n.documents,
            references=n.references,
            unresolved=n.unresolved,
            cross_norma=n.cross_norma,
        )
        for n in list_normas(session)
    ]


def _node(node: str, data: dict[str, Any]) -> GraphNodeOut:
    return GraphNodeOut(
        id=node,
        code=data["code"],
        norma=data["norma"],
        title=data["title"],
        document_type=data["document_type"],
        system_code=data["system_code"],
        file_format=data["file_format"],
        status=data["status"],
        resolved=data["resolved"],
        active=data["active"],
    )


def _edge(source: str, target: str, data: dict[str, Any]) -> GraphEdgeOut:
    return GraphEdgeOut(
        id=f"{source}->{target}",
        source=source,
        target=target,
        group=data["group"],
        occurrences=data["occurrences"],
        mixed_groups=data["mixed_groups"],
        cross_norma=data["cross_norma"],
    )


@router.get("/graph", response_model=GraphResponse, responses=ERRORS)
def graph_neighborhood(
    session: SessionDep,
    settings: SettingsDep,
    cache: CacheDep,
    code: Annotated[str, Query(description="Documento central del subgrafo")],
    norma: NormaQuery = None,
    depth: Annotated[int | None, Query(description="Saltos desde el documento")] = None,
    direction: Annotated[
        Literal["in", "out", "both"],
        Query(description="in: quienes lo citan · out: lo que cita · both: ambos"),
    ] = "both",
    types: Annotated[list[str] | None, Query(description="Tipos de documento a mostrar")] = None,
    groups: Annotated[list[str] | None, Query(description="Grupos de relación")] = None,
    include_unresolved: bool = True,
    max_nodes: Annotated[int | None, Query(ge=1)] = None,
) -> GraphResponse:
    """Subgrafo de vecindad (atraviesa normas), listo para Cytoscape.js."""
    depth = depth if depth is not None else settings.default_depth
    check_depth(depth, settings.max_depth)
    root = resolve_node(session, normalize_code(code), norma)
    filters = GraphFilters(
        groups=frozenset(groups) if groups else None, include_unresolved=include_unresolved
    )
    full = cache.get(session, filters)
    limit = min(max_nodes or settings.graph_max_nodes, settings.graph_max_nodes)
    hood = neighborhood(full, root, depth, direction, limit)

    wanted_types = {t.upper() for t in types} if types else None
    nodes = [
        node
        for node in hood.graph.nodes
        if node == root or wanted_types is None or full.nodes[node]["document_type"] in wanted_types
    ]
    sub = hood.graph.subgraph(nodes)
    return GraphResponse(
        root=root,
        depth=depth,
        direction=direction,
        truncated=hood.truncated,
        nodes=[
            NeighborhoodNodeOut(
                **_node(node, data).model_dump(),
                distance=hood.distances[node],
                is_root=node == root,
            )
            for node, data in sorted(
                sub.nodes(data=True), key=lambda n: (hood.distances[n[0]], n[0])
            )
        ],
        edges=[
            _edge(source, target, data) for source, target, data in sorted(sub.edges(data=True))
        ],
    )


@router.get("/graph/full", response_model=FullGraphResponse, responses=ERRORS)
def graph_full(
    session: SessionDep,
    settings: SettingsDep,
    cache: CacheDep,
    include_unresolved: bool = True,
) -> FullGraphResponse:
    """Grafo completo (todas las normas) para la vista de resaltado; acotado por
    ``ISO_GRAPH_FULL_MAX_NODES``."""
    full = cache.get(session, GraphFilters(include_unresolved=include_unresolved))
    if full.number_of_nodes() > settings.graph_full_max_nodes:
        raise GraphTooLargeError(
            f"El grafo tiene {full.number_of_nodes()} nodos y el máximo es "
            f"{settings.graph_full_max_nodes}; usar la vista de vecindad"
        )
    return FullGraphResponse(
        graph_version=get_graph_version(session),
        normas=sorted({data["norma"] for _, data in full.nodes(data=True) if data["norma"]}),
        nodes=[_node(node, data) for node, data in sorted(full.nodes(data=True))],
        edges=[
            _edge(source, target, data) for source, target, data in sorted(full.edges(data=True))
        ],
    )


@router.get("/graph/cycles", response_model=CyclesResponse, responses=ERRORS)
def cycles(
    session: SessionDep,
    cache: CacheDep,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> CyclesResponse:
    return CyclesResponse(cycles=find_cycles(cache.get(session), limit=limit))


@router.get("/stats", response_model=StatsResponse)
def stats(session: SessionDep) -> StatsResponse:
    return StatsResponse(**queries.stats(session))
