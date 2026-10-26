"""Log de cada corrida de ingesta: un archivo por corrida con todo lo que ocurrió.

Cada línea es ``fecha nivel evento clave=valor …`` para poder leerla y filtrarla con grep.
Los eventos se emiten también por el logger ``iso_trace.ingest`` (la CLI lo muestra en
consola con ``--verbose``). Los logs contienen nombres de documentos internos: la carpeta
debe quedar fuera de Git (``data/`` ya está ignorada).
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

LOGGER_NAME = "iso_trace.ingest"
_LINE_FORMAT = "%(asctime)s %(levelname)-7s %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def format_fields(event: str, fields: dict[str, Any]) -> str:
    parts = [event]
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={_format_value(value)}")
    return " ".join(parts)


def _format_value(value: Any) -> str:
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=isinstance(value, dict))
    text = str(value)
    if not text or any(ch.isspace() or ch in '="' for ch in text):
        return json.dumps(text, ensure_ascii=False)
    return text


class RunLogger:
    """Registra los eventos de una corrida en su propio archivo (si hay carpeta de logs)."""

    def __init__(
        self,
        log_dir: Path | None,
        *,
        run_id: int | None,
        level: str = "INFO",
        started_at: datetime | None = None,
    ) -> None:
        # Hora local, igual que las líneas del log (la base guarda las fechas en UTC).
        started = started_at or datetime.now().astimezone()
        label = f"{run_id:05d}" if run_id is not None else "simulacion"
        # Un logger hijo por corrida: el handler de archivo no se mezcla con otras corridas.
        self._logger = logging.getLogger(f"{LOGGER_NAME}.run-{label}-{id(self)}")
        self._logger.setLevel(level.upper())
        self._handler: logging.Handler | None = None
        self.path: Path | None = None
        if log_dir is not None:
            log_dir.mkdir(parents=True, exist_ok=True)
            self.path = log_dir / f"ingest-{label}-{started:%Y%m%d-%H%M%S}.log"
            self._handler = logging.FileHandler(self.path, encoding="utf-8")
            self._handler.setFormatter(logging.Formatter(_LINE_FORMAT, _DATE_FORMAT))
            self._logger.addHandler(self._handler)

    def info(self, event: str, **fields: Any) -> None:
        self._logger.info(format_fields(event, fields))

    def warning(self, event: str, **fields: Any) -> None:
        self._logger.warning(format_fields(event, fields))

    def error(self, event: str, **fields: Any) -> None:
        self._logger.error(format_fields(event, fields))

    def exception(self, event: str, exc: BaseException, **fields: Any) -> None:
        """Error con su traceback completo."""
        self._logger.error(format_fields(event, {**fields, "error": str(exc)}), exc_info=exc)

    def log(self, level: int, event: str, **fields: Any) -> None:
        self._logger.log(level, format_fields(event, fields))

    def close(self) -> None:
        if self._handler is not None:
            self._logger.removeHandler(self._handler)
            self._handler.close()
            self._handler = None
