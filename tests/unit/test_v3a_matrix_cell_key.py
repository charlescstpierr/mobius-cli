"""Unit tests for MatrixPipeline's private cell-key implementation.

Per PRD F10 and CONTEXT.md, a *Product matrix* cell is identified by a
canonical, deterministic ``cell_key`` that preserves the axis order
declared in the *Spec* — never alphabetical, never Python-dict order.

The public Module is now ``mobius.v3a.matrix.pipeline``; the cell-key
Implementation is intentionally private to keep key generation local to the
pipeline seam.
"""

from __future__ import annotations

from mobius.v3a.matrix.pipeline import _cell_key_from_combination, _iter_matrix_cells


def test_cell_key_from_single_axis_combination_uses_axis_equals_value() -> None:
    key = _cell_key_from_combination((("platform", "ios"),))

    assert key == "platform=ios"


def test_cell_key_from_multi_axis_preserves_declared_order() -> None:
    declared_order = _cell_key_from_combination(
        (("platform", "ios"), ("python", "3.12")),
    )
    reversed_order = _cell_key_from_combination(
        (("python", "3.12"), ("platform", "ios")),
    )

    assert declared_order == "platform=ios,python=3.12"
    assert reversed_order == "python=3.12,platform=ios"
    assert declared_order != reversed_order


def test_iter_matrix_cells_of_empty_matrix_yields_nothing() -> None:
    assert list(_iter_matrix_cells({})) == []


def test_iter_matrix_cells_yields_cartesian_product_in_declared_order() -> None:
    matrix = {"platform": ["ios", "android"], "python": ["3.12", "3.13"]}

    cells = list(_iter_matrix_cells(matrix))

    assert cells == [
        (("platform", "ios"), ("python", "3.12")),
        (("platform", "ios"), ("python", "3.13")),
        (("platform", "android"), ("python", "3.12")),
        (("platform", "android"), ("python", "3.13")),
    ]


def test_iter_matrix_cells_preserves_axis_declaration_order() -> None:
    # python first, then platform: the iterator must follow declaration, not
    # alphabetical or any other reordering.
    matrix = {"python": ["3.12"], "platform": ["ios", "android"]}

    cells = list(_iter_matrix_cells(matrix))

    assert cells == [
        (("python", "3.12"), ("platform", "ios")),
        (("python", "3.12"), ("platform", "android")),
    ]
