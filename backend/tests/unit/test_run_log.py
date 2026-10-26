"""Formato de las líneas del log de corrida."""

from pathlib import Path

from app.services.run_log import RunLogger, format_fields


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
