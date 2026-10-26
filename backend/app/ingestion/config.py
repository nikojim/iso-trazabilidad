"""Parámetros de delimitación de la sección REFERENCIAS, ampliables con un TOML opcional."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from app.ingestion.normalize import heading_key

DEFAULT_GROUP = "general"


@dataclass(frozen=True, slots=True)
class ExtractionConfig:
    # Claves de encabezado (ver normalize.heading_key) que abren la sección.
    section_aliases: frozenset[str] = frozenset({"referencias"})
    # Encabezados que cierran la sección aunque no tengan numeración ni nivel conocido.
    terminators: frozenset[str] = frozenset(
        {
            "historial",
            "control de cambios",
            "definiciones",
            "descripcion",
            "anexos",
            "anexo",
            "aprobaciones",
            "registros",
            "desarrollo",
            "objetivo",
            "alcance",
            "responsabilidades",
        }
    )
    # Subtítulos que cambian el grupo de aparición sin cerrar la sección.
    subgroups: dict[str, str] = field(default_factory=lambda: {"procedimientos": "procedimientos"})
    # Encabezados que abren una tabla de contenido.
    toc_titles: frozenset[str] = frozenset(
        {"tabla de contenido", "tabla de contenidos", "indice", "contenido"}
    )


def load_extraction_config(path: Path | None) -> ExtractionConfig:
    """Combina los valores por defecto con ``[referencias]`` de un archivo TOML.

    Ejemplo::

        [referencias]
        section_aliases = ["referencias", "documentos de referencia"]
        terminators = ["historial", "anexos"]
        subgroups = { "procedimientos" = "procedimientos", "registros" = "registros" }
    """
    default = ExtractionConfig()
    if path is None:
        return default
    with path.open("rb") as handle:
        data = tomllib.load(handle).get("referencias", {})

    def keys(name: str, fallback: frozenset[str]) -> frozenset[str]:
        values = data.get(name)
        return frozenset(heading_key(v) for v in values) if values is not None else fallback

    subgroups = data.get("subgroups")
    return ExtractionConfig(
        section_aliases=keys("section_aliases", default.section_aliases),
        terminators=keys("terminators", default.terminators),
        subgroups=(
            {heading_key(k): v for k, v in subgroups.items()}
            if subgroups is not None
            else default.subgroups
        ),
        toc_titles=keys("toc_titles", default.toc_titles),
    )
