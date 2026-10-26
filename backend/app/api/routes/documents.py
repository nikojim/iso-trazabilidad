"""Búsqueda, detalle, referencias, impacto y dependencias de documentos."""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.api.deps import (
    DEFAULT_PAGE_SIZE,
    CacheDep,
    NormaQuery,
    PageDep,
    PageSizeDep,
    SessionDep,
    SettingsDep,
)
from app.schemas.common import ErrorResponse, Page
from app.schemas.documents import DocumentDetail, DocumentSummary, ReferencesResponse
from app.schemas.graph import RootOut, TraversalItemOut, TraversalResponse, TraversalSummary
from app.services import catalog
from app.services.graph import GraphFilters
from app.services.impact import (
    TraversalResult,
    dependencies_of,
    impact_to_csv,
    impacted_by,
)

router = APIRouter(prefix="/documents", tags=["documentos"])
ERRORS = {
    400: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}
TypesQuery = Annotated[
    list[str] | None, Query(description="Mostrar solo estos tipos (PR, PO…); se recorre por todos")
]
GroupsQuery = Annotated[
    list[str] | None, Query(description="Seguir solo relaciones de estos grupos")
]


@router.get("", response_model=Page[DocumentSummary], responses=ERRORS)
def search(
    session: SessionDep,
    query: Annotated[str | None, Query(description="Texto en código o título")] = None,
    norma: NormaQuery = None,
    type: Annotated[str | None, Query(description="Prefijo: PO, PR, ES…")] = None,
    system: Annotated[str | None, Query(description="Sistema: SGS, SGSA, SGC…")] = None,
    folder: Annotated[str | None, Query(description="Carpeta (prefijo de la ruta)")] = None,
    status: Annotated[str | None, Query(description="Estado de extracción")] = None,
    active: bool | None = True,
    sort: Annotated[
        catalog.SortField, Query(description="norma: por norma y nombre (por defecto)")
    ] = "norma",
    page: PageDep = 1,
    page_size: PageSizeDep = DEFAULT_PAGE_SIZE,
) -> Page[DocumentSummary]:
    items, total = catalog.search_documents(
        session,
        query=query,
        norma=norma,
        document_type=type,
        system=system,
        folder=folder,
        status=status,
        active=active,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{code}", response_model=DocumentDetail, responses=ERRORS)
def detail(session: SessionDep, code: str, norma: NormaQuery = None) -> DocumentDetail:
    code = catalog.normalize_code(code)
    return catalog.get_document(session, catalog.resolve_norma(session, code, norma), code)


@router.get("/{code}/references", response_model=ReferencesResponse, responses=ERRORS)
def references(
    session: SessionDep,
    code: str,
    norma: NormaQuery = None,
    group: Annotated[str | None, Query(description="Solo este grupo")] = None,
) -> ReferencesResponse:
    """Salientes (lo que cita), pendientes (citados sin documento) y entrantes (quién lo cita)."""
    code = catalog.normalize_code(code)
    result = catalog.references_of(session, catalog.resolve_norma(session, code, norma), code)
    if group:
        result.outgoing = [r for r in result.outgoing if r.group == group]
        result.unresolved = [r for r in result.unresolved if r.group == group]
        result.incoming = [r for r in result.incoming if r.group == group]
    return result


def _traverse(
    session: SessionDep,
    settings: SettingsDep,
    cache: CacheDep,
    code: str,
    norma: str | None,
    depth: int | None,
    types: list[str] | None,
    groups: list[str] | None,
    *,
    impact: bool,
) -> TraversalResult:
    node = catalog.resolve_node(session, catalog.normalize_code(code), norma)
    filters = GraphFilters(groups=frozenset(groups) if groups else None)
    traverse = impacted_by if impact else dependencies_of
    return traverse(
        cache.get(session, filters),
        node,
        depth if depth is not None else settings.default_depth,
        max_depth=settings.max_depth,
        types=frozenset(t.upper() for t in types) if types else None,
    )


def _response(result: TraversalResult) -> TraversalResponse:
    def items(selected: list) -> list[TraversalItemOut]:  # type: ignore[type-arg]
        return [
            TraversalItemOut(
                code=i.code,
                norma=i.norma,
                node_id=i.node_id,
                title=i.title,
                document_type=i.document_type,
                depth=i.depth,
                relation=i.relation,
                path=list(i.path),
                resolved=i.resolved,
            )
            for i in selected
        ]

    return TraversalResponse(
        kind=result.kind,
        root=RootOut(
            code=result.root_code,
            norma=result.root_norma,
            node_id=result.root_node_id,
            title=result.root_title,
            resolved=result.root_resolved,
        ),
        depth=result.depth,
        disclaimer=result.disclaimer,
        direct=items(result.direct),
        indirect=items(result.indirect),
        summary=TraversalSummary(**result.summary()),
    )


@router.get("/{code}/impact", response_model=TraversalResponse, responses=ERRORS)
def impact(
    session: SessionDep,
    settings: SettingsDep,
    cache: CacheDep,
    code: str,
    norma: NormaQuery = None,
    depth: int | None = None,
    types: TypesQuery = None,
    groups: GroupsQuery = None,
) -> TraversalResponse:
    """Posibles documentos a revisar si cambia ``code``: quienes lo citan, directa o
    indirectamente, con la ruta que explica cada caso."""
    return _response(
        _traverse(session, settings, cache, code, norma, depth, types, groups, impact=True)
    )


@router.get(
    "/{code}/impact.csv",
    responses={**ERRORS, 200: {"content": {"text/csv": {}}}},
    response_class=Response,
)
def impact_csv(
    session: SessionDep,
    settings: SettingsDep,
    cache: CacheDep,
    code: str,
    norma: NormaQuery = None,
    depth: int | None = None,
    types: TypesQuery = None,
    groups: GroupsQuery = None,
) -> Response:
    """El mismo impacto en CSV para Excel (UTF-8 con BOM, separador ``;``)."""
    result = _traverse(session, settings, cache, code, norma, depth, types, groups, impact=True)
    filename = f"impacto-{result.root_code}.csv"
    return Response(
        content=impact_to_csv(result).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/{code}/dependencies", response_model=TraversalResponse, responses=ERRORS)
def dependencies(
    session: SessionDep,
    settings: SettingsDep,
    cache: CacheDep,
    code: str,
    norma: NormaQuery = None,
    depth: int | None = None,
    types: TypesQuery = None,
    groups: GroupsQuery = None,
) -> TraversalResponse:
    """Documentos que ``code`` cita, directa o indirectamente."""
    return _response(
        _traverse(session, settings, cache, code, norma, depth, types, groups, impact=False)
    )
