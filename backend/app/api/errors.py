"""Formato de error uniforme: ``{"error": {"code", "message", "details"}}``."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.services.catalog import CodeNotFoundError, NormaRequiredError, UnknownNormaError
from app.services.graph import DocumentNotInGraphError
from app.services.impact import DepthOutOfRangeError


class GraphTooLargeError(ValueError):
    """El grafo completo supera el tope configurado de nodos."""


logger = logging.getLogger(__name__)


def error_response(
    status: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(CodeNotFoundError)
    @app.exception_handler(DocumentNotInGraphError)
    async def not_found(_: Request, exc: LookupError) -> JSONResponse:
        return error_response(404, "document_not_found", str(exc))

    @app.exception_handler(UnknownNormaError)
    async def norma_not_found(_: Request, exc: LookupError) -> JSONResponse:
        return error_response(404, "norma_not_found", str(exc))

    @app.exception_handler(NormaRequiredError)
    async def norma_required(_: Request, exc: NormaRequiredError) -> JSONResponse:
        return error_response(
            409, "norma_required", str(exc), {"code": exc.code, "normas": exc.normas}
        )

    @app.exception_handler(GraphTooLargeError)
    async def graph_too_large(_: Request, exc: GraphTooLargeError) -> JSONResponse:
        return error_response(400, "graph_too_large", str(exc))

    @app.exception_handler(DepthOutOfRangeError)
    async def depth_out_of_range(_: Request, exc: DepthOutOfRangeError) -> JSONResponse:
        return error_response(400, "depth_out_of_range", str(exc))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return error_response(422, "validation_error", "Parámetros inválidos", {"errors": errors})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "http_error"
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def internal_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Error no controlado", exc_info=exc)
        return error_response(500, "internal_error", "Error interno del servidor")
