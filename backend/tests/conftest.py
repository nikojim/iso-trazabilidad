from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import migrate
from app.db.session import create_db_engine, dispose_engines, make_session_factory
from app.models import Document, ExtractionStatus, FileFormat


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Cada test arranca sin variables ISO_* heredadas y con cachés limpias; los logs de
    ingesta van a la carpeta temporal del test, nunca a data/logs del repositorio."""
    import os

    for name in list(os.environ):
        if name.startswith("ISO_") and name not in {"ISO_REAL_SAMPLES_DIR", "ISO_GOLDEN_SET"}:
            monkeypatch.delenv(name)
    monkeypatch.setenv("ISO_LOG_DIR", str(tmp_path / "logs"))
    get_settings.cache_clear()
    dispose_engines()
    yield
    get_settings.cache_clear()
    dispose_engines()


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'iso.db').as_posix()}"


@pytest.fixture
def migrated_engine(db_url: str) -> Iterator[Engine]:
    migrate.upgrade(db_url)
    engine = create_db_engine(db_url)
    yield engine
    engine.dispose()


@pytest.fixture
def session(migrated_engine: Engine) -> Iterator[Session]:
    with make_session_factory(migrated_engine)() as session:
        yield session
        session.rollback()


@pytest.fixture
def make_document() -> Callable[..., Document]:
    def factory(code: str = "PO-SGS-400", **overrides: Any) -> Document:
        doc_type, system, _ = code.split("-")
        values: dict[str, Any] = {
            "norma": "A",
            "code": code,
            "document_type": doc_type,
            "system_code": system,
            "title": f"Documento {code}",
            "version": "01",
            "file_path": f"A/{code}-01 Documento.pdf",
            "file_format": FileFormat.PDF,
            "file_size": 1024,
            "file_mtime": datetime(2026, 1, 1, tzinfo=UTC),
            "sha256": "0" * 64,
            "extraction_status": ExtractionStatus.OK,
        }
        values.update(overrides)
        return Document(**values)

    return factory
