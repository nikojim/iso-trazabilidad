"""El frontend genera sus tipos desde ``frontend/openapi.json``: debe coincidir con la API."""

import json
from pathlib import Path

from app.api.main import create_app
from app.config import Settings

FRONTEND_SCHEMA = Path(__file__).resolve().parents[3] / "frontend" / "openapi.json"


def test_frontend_schema_matches_the_api(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, database_url=f"sqlite:///{(tmp_path / 'x.db').as_posix()}")
    current = create_app(settings).openapi()
    committed = json.loads(FRONTEND_SCHEMA.read_text("utf-8"))

    assert committed == current, (
        "frontend/openapi.json está desactualizado: ejecutar `npm run gen:api` en frontend/"
    )
