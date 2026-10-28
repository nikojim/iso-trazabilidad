"""Formato de las líneas del log de corrida y depuración de logs viejos."""

import os
from datetime import datetime
from pathlib import Path

from app.services.run_log import RunLogger, format_fields, prune_logs


def test_fields_are_key_value_and_quoted_when_needed() -> None:
    line = format_fields(
        "documento",
        {
            "ruta": "A/MC-SGG-435-23 Manual.pdf",
            "codigo": "MC-SGG-435",
            "referencias": 3,
            "ambiguas": ["ES-SGC-001"],
            "motivo": None,
        },
    )

    assert line == (
        'documento ruta="A/MC-SGG-435-23 Manual.pdf" codigo=MC-SGG-435 referencias=3 '
        'ambiguas=["ES-SGC-001"]'
    )


def test_one_file_per_run_with_traceback_for_errors(tmp_path: Path) -> None:
    log = RunLogger(tmp_path / "logs", run_id=7)
    log.info("inicio", corrida=7)
    try:
        raise ValueError("falla de prueba")
    except ValueError as exc:
        log.exception("error_guardado", exc, ruta="A/x.pdf")
    log.close()

    assert log.path is not None and log.path.name.startswith("ingest-00007-")
    text = log.path.read_text("utf-8")
    assert "INFO    inicio corrida=7" in text
    assert 'ERROR   error_guardado ruta=A/x.pdf error="falla de prueba"' in text
    assert "Traceback" in text and "ValueError: falla de prueba" in text


def test_without_log_dir_nothing_is_written(tmp_path: Path) -> None:
    log = RunLogger(None, run_id=1)
    log.info("inicio")
    log.close()

    assert log.path is None


def make_logs(folder: Path, days_old: list[int], now: datetime) -> list[Path]:
    """Un log por antigüedad en días, del más nuevo al más viejo."""
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for index, days in enumerate(days_old):
        path = folder / f"ingest-{index:05d}-x.log"
        path.write_text("x", encoding="utf-8")
        stamp = now.timestamp() - days * 86400
        os.utime(path, (stamp, stamp))
        paths.append(path)
    return paths


def test_prune_keeps_the_most_recent_logs(tmp_path: Path) -> None:
    now = datetime(2026, 10, 26, 12, 0)
    logs = make_logs(tmp_path, [0, 1, 2, 3, 4], now)
    (tmp_path / "otro.txt").write_text("no es un log", encoding="utf-8")

    deleted = prune_logs(tmp_path, keep=3, max_age_days=0, exclude=logs[0], now=now)

    assert sorted(deleted) == logs[3:]  # la corrida en curso cuenta entre las 3
    assert sorted(tmp_path.iterdir()) == [*logs[:3], tmp_path / "otro.txt"]


def test_prune_by_age_never_deletes_the_current_run(tmp_path: Path) -> None:
    now = datetime(2026, 10, 26, 12, 0)
    logs = make_logs(tmp_path, [40, 10, 31, 45], now)

    deleted = prune_logs(tmp_path, keep=0, max_age_days=30, exclude=logs[0], now=now)

    assert sorted(deleted) == [logs[2], logs[3]]
    assert logs[0].exists() and logs[1].exists()


def test_prune_without_limits_or_folder_does_nothing(tmp_path: Path) -> None:
    logs = make_logs(tmp_path, [100, 200], datetime.now())

    assert prune_logs(tmp_path, keep=0, max_age_days=0) == []
    assert prune_logs(tmp_path / "no-existe", keep=1, max_age_days=1) == []
    assert all(path.exists() for path in logs)
