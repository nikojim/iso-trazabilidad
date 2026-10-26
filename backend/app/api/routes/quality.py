"""Incidencias, referencias pendientes e historial de ingestas."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DEFAULT_PAGE_SIZE, NormaQuery, PageDep, PageSizeDep, SessionDep
from app.schemas.common import ErrorResponse, Page
from app.schemas.documents import IssueOut
from app.schemas.graph import RunOut, UnresolvedOut
from app.services import catalog

router = APIRouter(tags=["calidad"])
ERRORS = {404: {"model": ErrorResponse}}


def _page[T](items: list[T], page: int, page_size: int) -> Page[T]:
    start = (page - 1) * page_size
    return Page(
        items=items[start : start + page_size], total=len(items), page=page, page_size=page_size
    )


@router.get("/quality/issues", response_model=Page[IssueOut], responses=ERRORS)
def issues(
    session: SessionDep,
    norma: NormaQuery = None,
    type: Annotated[str | None, Query(description="Tipo de incidencia")] = None,
    severity: Annotated[str | None, Query(description="info, warning o error")] = None,
    code: str | None = None,
    open: Annotated[bool, Query(description="Solo abiertas")] = True,
    derived: Annotated[bool, Query(description="Incluir las calculadas sobre el grafo")] = True,
    page: PageDep = 1,
    page_size: PageSizeDep = DEFAULT_PAGE_SIZE,
) -> Page[IssueOut]:
    """Incidencias de la ingesta (almacenadas) y derivadas (ciclos, títulos citados, etc.)."""
    found = catalog.list_issues(
        session,
        norma=norma,
        issue_type=type,
        severity=severity,
        code=code.strip().upper() if code else None,
        open_only=open,
        include_derived=derived,
    )
    return _page(found, page, page_size)


@router.get("/references/unresolved", response_model=Page[UnresolvedOut], responses=ERRORS)
def unresolved(
    session: SessionDep,
    norma: NormaQuery = None,
    query: Annotated[str | None, Query(description="Texto en el código citado")] = None,
    page: PageDep = 1,
    page_size: PageSizeDep = DEFAULT_PAGE_SIZE,
) -> Page[UnresolvedOut]:
    """Códigos citados sin destino: sin documento, o presentes en varias normas (ambiguos)."""
    return _page(catalog.unresolved_list(session, norma, query), page, page_size)


@router.get("/ingestion/runs", response_model=Page[RunOut])
def runs(
    session: SessionDep, page: PageDep = 1, page_size: PageSizeDep = DEFAULT_PAGE_SIZE
) -> Page[RunOut]:
    items, total = catalog.list_runs(session, page, page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)
