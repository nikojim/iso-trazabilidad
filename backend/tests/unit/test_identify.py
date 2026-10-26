from pathlib import Path

import pytest

from app.ingestion.identify import identify_source
from app.ingestion.normalize import normalize_text
from app.ingestion.types import BlockKind, DocumentContent, TextBlock
from app.models.enums import CodeSource, FileFormat

HEADER = "MC-SGG-435 / 23 - Manual de los Sistemas de Gestión - Página 2/36"
COVER = "Referencia/Versión : MC-SGG-435/23"


def content(
    *lines: str, header_texts: list[str] | None = None, **metadata: object
) -> DocumentContent:
    blocks = [
        TextBlock(normalize_text(t), t, BlockKind.LINE, page=1 if i < 3 else 2)
        for i, t in enumerate(lines)
    ]
    return DocumentContent(
        FileFormat.PDF, blocks, metadata=dict(metadata), header_texts=header_texts or []
    )


def test_filename_and_content_agree() -> None:
    identity = identify_source(
        Path("MC-SGG-435-23 Manual de los Sistemas de Gestión v2.pdf"), content(COVER, HEADER)
    )

    assert identity.code == "MC-SGG-435"
    assert identity.version == "23"
    assert identity.code_source is CodeSource.FILENAME_AND_CONTENT
    assert identity.title == "Manual de los Sistemas de Gestión"
    assert identity.issues == ()


def test_filename_only() -> None:
    identity = identify_source(Path("PO-SGSA-918-02 Política de Gestión de Cambios.pdf"), content())

    assert (identity.code, identity.version, identity.code_source) == (
        "PO-SGSA-918",
        "02",
        CodeSource.FILENAME,
    )
    assert identity.title == "Política de Gestión de Cambios"


def test_filename_contradicted_by_content_is_not_published() -> None:
    identity = identify_source(Path("PO-SGSA-918-02 Política.pdf"), content(COVER))

    assert identity.code is None
    assert [i.type for i in identity.issues] == ["source_code_conflict"]


def test_content_sources_disagreeing_is_a_conflict() -> None:
    other_header = "PO-SGS-400 / 23 - Otro - Página 2/5"
    identity = identify_source(Path("sin codigo.pdf"), content(COVER, other_header))

    assert identity.code is None
    assert identity.issues[0].type == "source_code_conflict"


def test_content_only_requires_two_agreeing_sources() -> None:
    both = identify_source(Path("manual.pdf"), content(COVER, HEADER))
    only_cover = identify_source(Path("manual.pdf"), content(COVER))

    assert (both.code, both.code_source) == ("MC-SGG-435", CodeSource.CONTENT)
    assert only_cover.code is None
    assert only_cover.issues[0].type == "source_code_missing"


def test_override_wins_and_is_validated() -> None:
    assert identify_source(Path("x.pdf"), content(), "po-sgs-400").code == "PO-SGS-400"
    assert (
        identify_source(Path("x.pdf"), content(), "po-sgs-400").code_source is CodeSource.OVERRIDE
    )
    assert identify_source(Path("x.pdf"), content(), "no valido").code is None


def test_version_mismatch_warns_and_prefers_content() -> None:
    identity = identify_source(Path("MC-SGG-435-22 Manual.pdf"), content(COVER))

    assert identity.version == "23"
    assert [i.type for i in identity.issues] == ["version_mismatch"]


def test_misaligned_cover_value_found_on_neighbor_line() -> None:
    identity = identify_source(
        Path("LC-SGSA-928-01 Listado.pdf"),
        content(
            "Nombre Listado de Informes", "LC-SGSA-928/01", "Referencia/Versión del formulario"
        ),
    )

    assert identity.code_source is CodeSource.FILENAME_AND_CONTENT
    assert identity.title == "Listado de Informes"


def test_docx_custom_property_and_word_header() -> None:
    identity = identify_source(
        Path("plantilla.docx"),
        content(
            header_texts=["RG-SGSA-930 / 01 - Informe de Incidente Grave - Página 1/3"],
            custom_properties={"Referencia": "RG-SGSA-930", "Version": "01"},
        ),
    )

    assert (identity.code, identity.version) == ("RG-SGSA-930", "01")
    assert identity.code_source is CodeSource.CONTENT
    assert identity.title == "Informe de Incidente Grave"


def test_document_kind_from_cover() -> None:
    identity = identify_source(
        Path("MC-SGG-435-23 Manual.pdf"), content("Tipo de documento : Manual")
    )

    assert identity.document_kind == "Manual"


@pytest.mark.parametrize("name", ["Manual.pdf", "ISO 20000 Inducción.pdf", "PO_SGS_400.pdf"])
def test_names_without_convention_have_no_code(name: str) -> None:
    assert identify_source(Path(name), content()).code is None
