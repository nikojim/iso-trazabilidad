from datetime import datetime

from pydantic import BaseModel


class RootOut(BaseModel):
    code: str
    norma: str | None
    node_id: str
    title: str | None
    resolved: bool


class TraversalItemOut(BaseModel):
    code: str
    norma: str | None  # None para un código citado sin documento
    node_id: str  # id del nodo en /api/graph y /api/graph/full
    title: str | None
    document_type: str
    depth: int
    relation: str  # "directo" o "indirecto"
    path: list[str]  # códigos en el sentido de las aristas: cada paso "cita a" el siguiente
    resolved: bool


class TraversalSummary(BaseModel):
    by_depth: dict[str, int]
    by_type: dict[str, int]


class TraversalResponse(BaseModel):
    kind: str  # "impact" o "dependencies"
    root: RootOut
    depth: int
    disclaimer: str
    direct: list[TraversalItemOut]
    indirect: list[TraversalItemOut]
    summary: TraversalSummary


class GraphNodeOut(BaseModel):
    id: str  # "norma/código" para documentos; el código para citados sin documento
    code: str
    norma: str | None
    title: str | None
    document_type: str
    system_code: str
    file_format: str | None
    status: str | None
    resolved: bool
    active: bool


class NeighborhoodNodeOut(GraphNodeOut):
    distance: int
    is_root: bool


class GraphEdgeOut(BaseModel):
    id: str
    source: str  # documento que cita
    target: str  # documento citado
    group: str
    occurrences: int
    mixed_groups: bool
    cross_norma: bool  # el citado está en otra norma


class GraphResponse(BaseModel):
    root: str  # id del nodo central
    depth: int
    direction: str
    truncated: bool
    nodes: list[NeighborhoodNodeOut]
    edges: list[GraphEdgeOut]


class FullGraphResponse(BaseModel):
    graph_version: int
    normas: list[str]
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]


class CyclesResponse(BaseModel):
    cycles: list[list[str]]


class UnresolvedOut(BaseModel):
    target_code: str
    title_hint: str | None
    cited_by_count: int
    cited_by: list[str]  # "norma/código" de quienes lo citan
    candidate_normas: list[str]  # si no está vacío, el código existe en varias normas (ambiguo)


class RunOut(BaseModel):
    id: int
    mode: str
    status: str
    root_path: str
    started_at: datetime
    ended_at: datetime | None
    processed_count: int
    skipped_count: int
    error_count: int
    warning_count: int
    new_count: int
    updated_count: int
    missing_count: int
    no_section_count: int
    unsupported_skipped_count: int
    root_files_count: int
    references_count: int
    occurrences_count: int
    duplicate_references_count: int
    unresolved_count: int
    log_path: str | None


class StatsResponse(BaseModel):
    normas: list[dict[str, object]]
    documents: int
    inactive_documents: int
    by_status: dict[str, int]
    by_type: dict[str, int]
    references: int
    unresolved_references: int
    open_issues: int
    graph_version: int
    last_run: dict[str, object] | None


class LimitsOut(BaseModel):
    default_depth: int
    max_depth: int
    graph_max_nodes: int
    graph_full_max_nodes: int


class HealthResponse(BaseModel):
    status: str
    database: str
    schema_revision: str | None
    graph_version: int
    limits: LimitsOut
