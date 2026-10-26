"""Aplicación FastAPI de solo lectura (la ingesta se hace por CLI)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_error_handlers
from app.api.routes import documents, graphs, quality
from app.config import Settings, get_settings
from app.db import migrate
from app.db.session import get_engine, make_session_factory
from app.services.graph import GraphCache


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        url = settings.database_url
        if migrate.current_revision(url) != migrate.head_revision(url):
            raise RuntimeError("La base no está inicializada: ejecutar 'iso-trace db init'")
        engine = get_engine(url)
        app.state.engine = engine
        app.state.session_factory = make_session_factory(engine)
        yield

    app = FastAPI(
        title="ISO Trace API",
        version="0.1.0",
        description=(
            "Consulta de trazabilidad documental ISO. Una arista A → B significa **A cita a B**. "
            "El impacto lista **posibles documentos a revisar**, no la confirmación de que deban "
            "modificarse. Hay un solo grafo: cada carpeta raíz del directorio de documentos es una "
            "norma, y las referencias pueden cruzar normas."
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.graph_cache = GraphCache()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    for router in (graphs.router, documents.router, quality.router):
        app.include_router(router, prefix="/api")
    return app


app = create_app()
