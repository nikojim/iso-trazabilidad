import pytest

from app.ingestion.normalize import heading_key, normalize_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("[ES‑SGC–001]", "[ES-SGC-001]"),  # guion no separable y semirraya
        ("[ES−SGC－001]", "[ES-SGC-001]"),  # signo menos y guion de ancho completo
        ("PO-SGS-400  Política", "PO-SGS-400 Política"),  # NBSP
        ("  línea\t con\n saltos  ", "línea con saltos"),
        ("［PR-SGG-101］", "[PR-SGG-101]"),  # corchetes de ancho completo (NFKC)
    ],
)
def test_normalize_text(raw: str, expected: str) -> None:
    assert normalize_text(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["REFERENCIAS", "4 REFERENCIAS", "4. Referencias:", "  4  referencias ", "Referéncias"],
)
def test_heading_key_ignores_numbering_case_accents_and_punctuation(raw: str) -> None:
    assert heading_key(raw) == "referencias"


def test_heading_key_keeps_inner_words() -> None:
    assert heading_key("7 DESCRIPCIÓN") == "descripcion"
    assert heading_key("Control de cambios") == "control de cambios"
