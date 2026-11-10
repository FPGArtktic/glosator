# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Code listings, laid out again from the characters on the page.

docling finds a listing and draws a box around it, but hands back its text
joined into one line: the line breaks and the indentation are gone, and in a
language with line comments the first "//" swallows the rest of the program.
The text layer still has every character where it was printed, so the lines
and columns are rebuilt from that.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from itertools import pairwise

from app import config
from app.pdf import Glyph

# Characters a typesetter puts in code for the look of it, each of which can
# only stand for the ASCII one in a program: a book set "p->x" with a minus
# sign, and a compiler, or a reader copying the note, would refuse it.
TYPESET_TO_ASCII = str.maketrans({"\u2212": "-", "\u2217": "*"})


def wanted(domain: str) -> bool:
    """True for a book whose listings belong in its notes."""
    return domain.strip().lower() in config.LISTING_DOMAINS


def formulas_wanted(domain: str) -> bool:
    """True for a book whose formulas are recognised and kept in its notes.

    A programming book's are not: recognition read its code as mathematics.
    """
    name = domain.strip().lower()
    return (
        name not in config.LISTING_DOMAINS
        or name in config.MATHEMATICAL_LISTING_DOMAINS
    )


def inside(
    glyphs: Sequence[Glyph], box: tuple[float, float, float, float]
) -> list[Glyph]:
    """The glyphs whose middle lies in ``box`` (left, bottom, right, top)."""
    left, bottom, right, top = box
    margin = config.LISTING_BOX_MARGIN_PT
    return [
        glyph
        for glyph in glyphs
        if left - margin <= (glyph.left + glyph.right) / 2 <= right + margin
        and bottom - margin <= glyph.middle <= top + margin
    ]


def layout(glyphs: Sequence[Glyph]) -> str:
    """The listing as text: one line per printed line, indentation kept."""
    if not glyphs:
        return ""
    cell = statistics.median(glyph.right - glyph.left for glyph in glyphs)
    lines = _lines(glyphs)
    code = [line for line in lines if _monospaced(line, cell)] or lines
    margin = min(line[0].left for line in code)
    text = "\n".join(_line_text(line, margin, cell) for line in lines)
    return text.translate(TYPESET_TO_ASCII)


def _lines(glyphs: Sequence[Glyph]) -> list[list[Glyph]]:
    """Glyphs grouped into printed lines, top line first, each left to right."""
    lines: list[list[Glyph]] = []
    for glyph in sorted(glyphs, key=lambda glyph: (-glyph.middle, glyph.left)):
        height = glyph.top - glyph.bottom
        if lines and abs(glyph.middle - lines[-1][0].middle) <= (
            config.LISTING_LINE_TOLERANCE * height
        ):
            lines[-1].append(glyph)
        else:
            lines.append([glyph])
    return [sorted(line, key=lambda glyph: glyph.left) for line in lines]


def _monospaced(line: Sequence[Glyph], cell: float) -> bool:
    """True when the line is set in the listing's own, monospaced font."""
    tolerance = config.LISTING_CELL_TOLERANCE * cell
    even = sum(abs(glyph.right - glyph.left - cell) <= tolerance for glyph in line)
    return even >= config.LISTING_MONOSPACED_SHARE * len(line)


def _line_text(line: Sequence[Glyph], margin: float, cell: float) -> str:
    text = " " * _spaces(line[0].left - margin, cell)
    for before, glyph in pairwise(line):
        spaces = _spaces(glyph.left - before.right, cell)
        if spaces == 0 and glyph.space_before:
            spaces = 1
        text += before.text + " " * spaces
    return text + line[-1].text


def _spaces(gap: float, cell: float) -> int:
    """How many spaces a horizontal gap stands for."""
    columns = round(gap / cell)
    if columns == 0 and gap > config.LISTING_WORD_GAP * cell:
        return 1
    return max(columns, 0)
