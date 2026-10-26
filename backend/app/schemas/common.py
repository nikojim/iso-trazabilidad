from typing import Any

from pydantic import BaseModel, Field

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


class ErrorBody(BaseModel):
    code: str = Field(examples=["document_not_found"])
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody
