"""Dependencias compartidas por las rutas."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Query, Request
from sqlalchemy.orm import Session

from app.config import Settings
from app.schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.services.graph import GraphCache


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_session(request: Request) -> Iterator[Session]:
    """Sesión de solo lectura: la API nunca escribe en la base."""
    with request.app.state.session_factory() as session:
        try:
            yield session
        finally:
            session.rollback()


def get_graph_cache(request: Request) -> GraphCache:
    return request.app.state.graph_cache


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
CacheDep = Annotated[GraphCache, Depends(get_graph_cache)]
PageDep = Annotated[int, Query(ge=1, description="Página (desde 1)")]
PageSizeDep = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE, description="Elementos por página")]
NormaQuery = Annotated[
    str | None,
    Query(description="Norma (carpeta raíz). Obligatoria si el código es documento en varias"),
]

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "CacheDep",
    "NormaQuery",
    "PageDep",
    "PageSizeDep",
    "SessionDep",
    "SettingsDep",
]
