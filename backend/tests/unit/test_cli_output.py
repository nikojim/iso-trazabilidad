import io
import sys

import pytest

from app.cli import _use_utf8_output


def test_redirected_cp1252_output_switches_to_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stream)

    _use_utf8_output()
    print("PR → MC · precisión ≥ 99%")
    stream.flush()

    assert raw.getvalue().decode("utf-8").strip() == "PR → MC · precisión ≥ 99%"
