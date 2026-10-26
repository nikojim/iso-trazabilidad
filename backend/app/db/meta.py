"""Acceso a la tabla ``meta``."""

from sqlalchemy.orm import Session

from app.models import Meta

GRAPH_VERSION = "graph_version"


def get_meta(session: Session, key: str) -> str | None:
    row = session.get(Meta, key)
    return row.value if row else None


def set_meta(session: Session, key: str, value: str) -> None:
    row = session.get(Meta, key)
    if row is None:
        session.add(Meta(key=key, value=value))
    else:
        row.value = value


def get_graph_version(session: Session) -> int:
    return int(get_meta(session, GRAPH_VERSION) or 0)


def bump_graph_version(session: Session) -> int:
    """Incrementa la versión del grafo; se llama en la misma transacción que la escritura."""
    version = get_graph_version(session) + 1
    set_meta(session, GRAPH_VERSION, str(version))
    return version
