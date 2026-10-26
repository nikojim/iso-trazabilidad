import pytest
from typer.testing import CliRunner

from app.cli import app
from app.db import migrate

runner = CliRunner()


def test_db_init_is_idempotent(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ISO_DATABASE_URL", db_url)

    first = runner.invoke(app, ["db", "init"])
    second = runner.invoke(app, ["db", "init"])

    assert first.exit_code == 0, first.output
    assert "Base migrada de vacía a 0003" in first.output
    assert second.exit_code == 0, second.output
    assert "ya está en la versión 0003" in second.output
    assert migrate.current_revision(db_url) == "0003"


def test_db_without_subcommand_shows_help() -> None:
    result = runner.invoke(app, ["db"])

    assert "init" in result.output
