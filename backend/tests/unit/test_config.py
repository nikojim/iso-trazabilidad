from pathlib import Path

import pytest

from app.config import Settings, get_settings


def test_defaults_keep_api_on_localhost() -> None:
    settings = Settings(_env_file=None)

    assert settings.database_url == "sqlite:///data/iso.db"
    assert settings.documents_dir == Path("data/documents")
    assert settings.api_host == "127.0.0.1"
    assert settings.max_depth == 10
    assert settings.default_depth == 2


def test_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ISO_DATABASE_URL", "sqlite:///otra.db")
    monkeypatch.setenv("ISO_MAX_DEPTH", "4")
    monkeypatch.setenv("ISO_CORS_ORIGINS", "http://a:1, http://b:2")

    settings = get_settings()

    assert settings.database_url == "sqlite:///otra.db"
    assert settings.max_depth == 4
    assert settings.cors_origin_list == ["http://a:1", "http://b:2"]


def test_depth_must_be_positive() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, max_depth=0)
