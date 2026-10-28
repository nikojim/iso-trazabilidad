"""Huella de las reglas de extracción: código del paquete ``app.ingestion`` + configuración.

Un documento extraído con otra huella se vuelve a procesar en ``--incremental`` aunque su
archivo no haya cambiado: así un cambio en el extractor o en ``ISO_EXTRACTION_CONFIG``
llega a todos los documentos sin depender de acordarse de correr una ingesta completa.
"""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.ingestion.config import ExtractionConfig

_PACKAGE = Path(__file__).resolve().parent


def extraction_fingerprint(config: ExtractionConfig) -> str:
    digest = hashlib.sha256()
    for path in sorted(_PACKAGE.rglob("*.py")):
        digest.update(path.relative_to(_PACKAGE).as_posix().encode() + b"\0")
        # Independiente del fin de línea con que Git dejó el archivo en cada equipo.
        digest.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    digest.update(json.dumps(_canonical(config), sort_keys=True).encode())
    return digest.hexdigest()


def _canonical(config: ExtractionConfig) -> dict[str, Any]:
    return {
        name: sorted(value) if isinstance(value, frozenset) else value
        for name, value in asdict(config).items()
    }
