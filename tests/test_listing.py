# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Rebuilding a code listing from the characters on the page."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import extract, listing
from app.pdf import Glyph

CELL = 6.0
HEIGHT = 10.0
LEADING = 12.0
MARGIN = 72.0
TOP = 700.0

PROGRAM = """\
int main(void)
{
    int total = 0;
    for (int i = 0; i < 4; i++)
        total += i;  // sum
    return total;
}"""


def monospaced(text: str, left: float = MARGIN, top: float = TOP) -> list[Glyph]:
    """The glyphs a monospaced font would print for ``text``."""
    glyphs = []
    for row, line in enumerate(text.splitlines()):
        line_top = top - row * LEADING
        for column, character in enumerate(line):
            if character == " ":
                continue
            x = left + column * CELL
            glyphs.append(Glyph(character, x, line_top - HEIGHT, x + CELL, line_top))
    return glyphs


def test_lines_and_indentation_come_back() -> None:
    assert listing.layout(monospaced(PROGRAM)) == PROGRAM


def test_the_order_glyphs_arrive_in_does_not_matter() -> None:
    assert listing.layout(list(reversed(monospaced(PROGRAM)))) == PROGRAM


def test_a_listing_indented_on_the_page_starts_at_column_zero() -> None:
    assert listing.layout(monospaced(PROGRAM, left=140.0)) == PROGRAM


def test_punctuation_set_lower_stays_on_its_line() -> None:
    glyphs = monospaced("a;b")
    low = glyphs[1]
    glyphs[1] = Glyph(low.text, low.left, low.bottom - 2, low.right, low.top - 2)
    assert listing.layout(glyphs) == "a;b"


def test_a_narrow_word_space_in_a_proportional_comment_is_kept() -> None:
    glyphs = monospaced("total;")
    left = glyphs[-1].right + CELL
    for word in ("ab", "cd"):
        for character in word:
            glyphs.append(Glyph(character, left, TOP - HEIGHT, left + 3.0, TOP))
            left += 3.0
        left += 2.5
    assert listing.layout(glyphs) == "total; ab cd"


def test_only_glyphs_in_the_box_belong_to_the_listing() -> None:
    glyphs = monospaced("in") + monospaced("out", left=400.0)
    box = (MARGIN, TOP - HEIGHT, MARGIN + 2 * CELL, TOP)
    assert listing.layout(listing.inside(glyphs, box)) == "in"


def test_no_glyphs_give_no_text() -> None:
    assert listing.layout([]) == ""


def test_listings_are_wanted_for_programming_books_only() -> None:
    assert listing.wanted("Programming")
    assert not listing.wanted("electronics")


def test_a_rebuilt_block_reaches_the_markdown_with_its_lines(monkeypatch) -> None:
    pytest.importorskip("docling_core")
    from docling_core.types.doc.base import BoundingBox, CoordOrigin, Size
    from docling_core.types.doc.document import DoclingDocument, ProvenanceItem

    document = DoclingDocument(name="sample")
    document.add_page(page_no=1, size=Size(width=595.0, height=842.0))
    lines = len(PROGRAM.splitlines())
    bbox = BoundingBox(
        l=MARGIN,
        t=TOP,
        r=MARGIN + 40 * CELL,
        b=TOP - (lines - 1) * LEADING - HEIGHT,
        coord_origin=CoordOrigin.BOTTOMLEFT,
    )
    flat = " ".join(PROGRAM.split())
    document.add_code(
        text=flat,
        prov=ProvenanceItem(page_no=1, bbox=bbox, charspan=(0, len(flat))),
    )
    monkeypatch.setattr(extract.pdf, "page_glyphs", lambda *_args: monospaced(PROGRAM))

    assert extract.rebuild_listings(document, Path("/b.pdf")) == 1
    assert PROGRAM in extract.page_markdown(document)


def test_a_programming_book_is_extracted_without_formulas() -> None:
    settings = extract._batch_settings(1, 2, "eng", 0, "", listings=True)
    assert settings["listings"] is True
    assert settings["formulas"] is False


def test_a_kerning_gap_inside_a_word_is_not_a_space() -> None:
    glyphs = monospaced("total;")
    left = glyphs[-1].right + CELL
    for character in "word":
        glyphs.append(Glyph(character, left, TOP - HEIGHT, left + 3.0, TOP))
        left += 3.3
    assert listing.layout(glyphs) == "total; word"


def test_a_word_space_a_fifth_of_a_cell_wide_is_kept() -> None:
    glyphs = monospaced("total;")
    left = glyphs[-1].right + CELL
    for word in ("do", "it"):
        for character in word:
            glyphs.append(Glyph(character, left, TOP - HEIGHT, left + 3.0, TOP))
            left += 3.0
        left += 1.2
    assert listing.layout(glyphs) == "total; do it"


def test_a_typeset_minus_and_asterisk_become_ascii() -> None:
    assert listing.layout(monospaced("p\u2212>next = \u2217q;")) == "p->next = *q;"


def test_a_word_break_the_text_layer_has_survives_a_closed_gap() -> None:
    glyphs = monospaced("ab")
    after = glyphs[-1]
    glyphs.append(
        Glyph("c", after.right, after.bottom, after.right + CELL, after.top, True)
    )
    assert listing.layout(glyphs) == "ab c"
