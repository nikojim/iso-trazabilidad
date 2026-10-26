"""Regla de resolución de códigos citados en el grafo único (CLAUDE.md, regla 11)."""

from app.services.resolution import Resolution, choose_target


def test_same_norma_wins_even_if_other_normas_have_the_code() -> None:
    assert choose_target("A", [(1, "A"), (2, "B"), (3, "C")]) == Resolution(1)


def test_single_copy_in_another_norma_is_a_cross_reference() -> None:
    assert choose_target("A", [(2, "B")]) == Resolution(2, cross_norma=True)


def test_several_other_normas_are_ambiguous() -> None:
    assert choose_target("A", [(3, "C"), (2, "B")]) == Resolution(None, ambiguous_normas=("B", "C"))


def test_no_document_leaves_the_reference_pending() -> None:
    assert choose_target("A", []) == Resolution(None)
