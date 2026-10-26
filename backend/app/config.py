"""Configuración de ISO Trace leída de variables de entorno con prefijo ``ISO_``."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ISO_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///data/iso.db"
    documents_dir: Path = Path("data/documents")

    max_depth: int = Field(default=10, ge=1)
    default_depth: int = Field(default=2, ge=1)
    graph_max_nodes: int = Field(default=300, ge=1)
    # Tope del grafo completo (vista de resaltado): por encima se pide usar la vecindad.
    graph_full_max_nodes: int = Field(default=3000, ge=1)

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173"

    # Un archivo de log por corrida de ingesta; None desactiva el archivo.
    log_dir: Path | None = Path("data/logs")
    log_level: str = "INFO"

    extraction_config: Path | None = None
    real_samples_dir: Path | None = None
    golden_set: Path | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
