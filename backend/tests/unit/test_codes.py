import pytest

from app.ingestion.codes import find_candidates, find_codes, split_code
from app.ingestion.normalize import normalize_text


def test_find_codes_with_title_hint() -> None:
    [match] = find_codes("[PO-SGS-400] Política de Seguridad de la Información")

    assert match.code == "PO-SGS-400"
    assert match.raw == "[PO-SGS-400]"
    assert match.title_hint == "Política de Seguridad de la Información"


@pytest.mark.parametrize(
    "text",
    ["[ es-sgc-001 ]", "[ES-SGC-001]", normalize_text("[ES‑SGC–001]")],
)
def test_find_codes_normalizes_case_spaces_and_dashes(text: str) -> None:
    assert [m.code for m in find_codes(text)] == ["ES-SGC-001"]


def test_find_codes_multiple_codes_split_title_hints() -> None:
    matches = find_codes("[PR-SGG-000] Control [PR-SGG-101] Personal")

    assert [(m.code, m.title_hint) for m in matches] == [
        ("PR-SGG-000", "Control"),
        ("PR-SGG-101", "Personal"),
    ]


def test_code_without_title_has_no_hint() -> None:
    assert find_codes("[AX-SGC-002]")[0].title_hint is None


@pytest.mark.parametrize(
    "text",
    ["[ES-SG-1]", "[ESX-SGC-001A]", "[ESXYZ-SGC-001]", "ES-SGC-001", "[ES SGC 001]"],
)
def test_invalid_or_unbracketed_codes_are_not_references(text: str) -> None:
    assert find_codes(text) == []


@pytest.mark.parametrize("text", ["ES-SGG-003", "ES-SGG-003 Especificaciones CRM", " es-sgg-003"])
def test_leading_unbracketed_code_accepted_only_when_allowed(text: str) -> None:
    assert find_codes(text) == []

    [match] = find_codes(text, allow_leading_unbracketed=True)

    assert match.code == "ES-SGG-003"
    assert not match.bracketed


@pytest.mark.parametrize(
    "text", ["Ver ES-SGG-003", "ES-SGG-0031X", "ES-S-003 Algo", "C-SGSA-915 Tabla"]
)
def test_leading_rule_needs_a_valid_code_at_the_start(text: str) -> None:
    assert find_codes(text, allow_leading_unbracketed=True) == []


def test_leading_code_followed_by_bracketed_code() -> None:
    matches = find_codes(
        "ES-SGG-003 Especificaciones [PO-SGS-400] Política", allow_leading_unbracketed=True
    )

    assert [(m.code, m.title_hint, m.bracketed) for m in matches] == [
        ("ES-SGG-003", "Especificaciones", False),
        ("PO-SGS-400", "Política", True),
    ]


def test_accepted_leading_code_is_not_a_candidate() -> None:
    assert find_candidates("ES-SGG-003 Especificaciones", allow_leading_unbracketed=True) == []
    assert find_candidates("ES-SGG-003 Especificaciones")[0].well_formed


def test_candidates_report_invalid_bracketed_codes() -> None:
    [candidate] = find_candidates("[ES-SG-1] Algo")

    assert candidate.bracketed
    assert not candidate.well_formed


def test_candidates_report_well_formed_code_without_brackets() -> None:
    [candidate] = find_candidates("Ver ES-SGC-001 Política")

    assert not candidate.bracketed
    assert candidate.well_formed


def test_candidates_report_malformed_unbracketed_code() -> None:
    [candidate] = find_candidates("C-SGSA-915 Tabla de Documentos")

    assert candidate.raw == "C-SGSA-915"
    assert not candidate.well_formed


def test_valid_references_and_plain_text_produce_no_candidates() -> None:
    assert find_candidates("[PO-SGS-400] Política ISO 20000-1 versión 2") == []


def test_split_code() -> None:
    assert split_code("AL-SGSA-911") == ("AL", "SGSA")
