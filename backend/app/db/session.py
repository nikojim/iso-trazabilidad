"""Engine y sesiones SQLAlchemy sobre SQLite."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from sqlite3 import Connection as SQLiteConnection
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

SQLITE_PRAGMAS = {
    "foreign_keys": "ON",
    "busy_timeout": "5000",
    "synchronous": "NORMAL",
}


def _set_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
    if not isinstance(dbapi_connection, SQLiteConnection):
        return
    cursor = dbapi_connection.cursor()
    try:
        for name, value in SQLITE_PRAGMAS.items():
            cursor.execute(f"PRAGMA {name}={value}")
        cursor.execute("PRAGMA journal_mode=WAL")
    finally:
        cursor.close()


def _ensure_sqlite_parent_dir(url: str) -> None:
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        return
    database = parsed.database
    if database and database != ":memory:":
        Path(database).parent.mkdir(parents=True, exist_ok=True)


def create_db_engine(url: str) -> Engine:
    """Crea un engine con los pragmas obligatorios aplicados a cada conexión."""
    _ensure_sqlite_parent_dir(url)
    engine = create_engine(url)
    event.listen(engine, "connect", _set_sqlite_pragmas)
    return engine


_engines: dict[str, Engine] = {}


def get_engine(url: str | None = None) -> Engine:
    """Engine compartido por URL (uno por proceso)."""
    url = url or get_settings().database_url
    if url not in _engines:
        _engines[url] = create_db_engine(url)
    return _engines[url]


def dispose_engines() -> None:
    """Cierra las conexiones de los engines compartidos (tests, cambio de configuración)."""
    for engine in _engines.values():
        engine.dispose()
    _engines.clear()


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    """Sesión transaccional: commit al salir, rollback ante cualquier excepción."""
    factory = make_session_factory(engine or get_engine())
    with factory() as session, session.begin():
        yield session
