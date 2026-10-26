from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from app.db.session import create_db_engine, session_scope
from app.models import Meta


def test_sqlite_pragmas_applied_on_every_connection(migrated_engine: Engine) -> None:
    for _ in range(2):
        with migrated_engine.connect() as connection:
            assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
            assert connection.execute(text("PRAGMA journal_mode")).scalar() == "wal"
            assert connection.execute(text("PRAGMA busy_timeout")).scalar() == 5000
            # NORMAL = 1
            assert connection.execute(text("PRAGMA synchronous")).scalar() == 1


def test_engine_creates_parent_directory(tmp_path: Path) -> None:
    db_file = tmp_path / "nested" / "dir" / "iso.db"
    engine = create_db_engine(f"sqlite:///{db_file.as_posix()}")
    with engine.connect():
        pass
    engine.dispose()

    assert db_file.exists()


def test_session_scope_rolls_back_on_error(migrated_engine: Engine) -> None:
    with pytest.raises(RuntimeError), session_scope(migrated_engine) as session:
        session.add(Meta(key="temporal", value="x"))
        session.flush()
        raise RuntimeError("falla simulada")

    with session_scope(migrated_engine) as session:
        assert session.get(Meta, "temporal") is None


def test_session_scope_commits(migrated_engine: Engine) -> None:
    with session_scope(migrated_engine) as session:
        session.add(Meta(key="persistido", value="1"))

    with session_scope(migrated_engine) as session:
        assert session.get(Meta, "persistido").value == "1"
