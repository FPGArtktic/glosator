# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""The letters of a broken mathematics font, read as what they show."""

from __future__ import annotations

import pytest

from app import mathfont

# Escapes, not the characters: the text layer's letters are Oriya, Tamil,
# Telugu and Ethiopic, and the mathematical italic ones look like ASCII.


@pytest.mark.parametrize(
    ("broken", "meant"),
    [
        # d_e(P_1, C_2) = sqrt((1-5)^2 ...), a distance in a k-means table
        (
            "\U0001d451\u0bd8\u123a\U0001d443\u0b35, \U0001d436\u0b36\u123b"
            " = \u0da5\u123a1-5\u123b \u0b36",
            "\U0001d451e(\U0001d4431, \U0001d4362) = \u221a(1-5) 2",
        ),
        # s with the subscript "biased", squared
        ("\U0001d460\u0bd5\u0bdc\u0bd4\u0be6\u0bd8\u0bd7 \u0b36", "\U0001d460biased 2"),
        # sigma with X_1 in its subscript: a subscript of a subscript
        ("\U0001d70e\u0bd1\u0c2d", "\U0001d70eX1"),
        # Y-hat of step t-1, and w transposed
        (
            "\U0001d480\u0de1\u123a\u0be7\u0b3f\u0b35\u123b, \U0001d498\u0bcd",
            "\U0001d480\u0302(t\u22121), \U0001d498T",
        ),
        # an interval on a page with no italic letter
        ("\u123e0, 100\u123f", "[0, 100]"),
    ],
)
def test_a_broken_math_font_reads_as_mathematics(broken: str, meant: str) -> None:
    assert mathfont.restore(broken) == meant


def test_a_page_without_mathematics_keeps_its_letters() -> None:
    text = "\u0b35 \u0b36 \u0bd8"
    assert mathfont.restore(text) == text
