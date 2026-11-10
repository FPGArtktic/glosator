# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""The letters of a mathematics font whose text layer names the wrong ones.

A book typeset in Word with Cambria Math reaches the PDF with a broken
character map for the font's script sizes and big delimiters: a subscript 1
reads as the Oriya letter "\u0b35", a parenthesis as the Ethiopic syllable
"\u123a". docling copies the text layer, so "x\u0b35" stood for x with a
subscript 1 in two of the books, and the model copied the garbage into the
notes. Each script size is one block of code points in alphabetical order,
so the map is an offset per block; the delimiters and signs were read off the
pages they stand on.

Whether a digit was set as a subscript or a superscript is not in the text
layer: both come back as the plain digit, which the text around it explains.
"""

from __future__ import annotations

import string

# The first letter, capital and small, and the first digit of each script
# size; the rest of the alphabet and the digits follow in order.
FIRST_SCRIPT_CAPITAL = 0x0BBA
FIRST_SCRIPT_SMALL = 0x0BD4
FIRST_SCRIPT_DIGIT = 0x0B34
FIRST_SECOND_SCRIPT_CAPITAL = 0x0CB2
FIRST_SECOND_SCRIPT_SMALL = 0x0CCC
FIRST_SECOND_SCRIPT_DIGIT = 0x0C2C

COMBINING_CIRCUMFLEX = "\u0302"
COMBINING_MACRON = "\u0304"

SIGNS = {
    # Signs at the first script size: "t\u0b3f1" is t-1 in a subscript.
    "\u0b3e": "+",
    "\u0b3f": "\u2212",
    "\u0b40": "=",
    # Delimiters, at text size and stretched around a fraction or a sum.
    "\u123a": "(",
    "\u123b": ")",
    "\u123c": "{",
    "\u123d": "}",
    "\u123e": "[",
    "\u123f": "]",
    "\u1240": "(",
    "\u1241": ")",
    "\u0d6b": "(",
    "\u0d6f": ")",
    "\u0d6c": "(",
    "\u0d70": ")",
    "\u0d63": "[",
    "\u0d67": "]",
    # Relations and operators.
    "\u0d4c": "=",
    "\u0d4f": "<",
    "\u0d52": "\u2265",
    "\u0da5": "\u221a",
    "\u0dcd": "\u2211",
    # Primes, at text size and in a subscript: max over a' of Q(s', a').
    "\u11f1": "\u2032",
    "\u11f2": "\u2032",
    # Accents over the letter before them: y-hat, alpha-bar.
    "\u0ddc": COMBINING_CIRCUMFLEX,
    "\u0ddd": COMBINING_CIRCUMFLEX,
    "\u0de1": COMBINING_CIRCUMFLEX,
    "\u0d24": COMBINING_MACRON,
    # A dotless i under a hat: the predicted y of observation i.
    "\u0b19": "i",
}


def _run(first: int, characters: str) -> dict[str, str]:
    return {chr(first + index): character for index, character in enumerate(characters)}


GLYPHS = str.maketrans(
    {
        **_run(FIRST_SCRIPT_CAPITAL, string.ascii_uppercase),
        **_run(FIRST_SCRIPT_SMALL, string.ascii_lowercase),
        **_run(FIRST_SCRIPT_DIGIT, string.digits),
        **_run(FIRST_SECOND_SCRIPT_CAPITAL, string.ascii_uppercase),
        **_run(FIRST_SECOND_SCRIPT_SMALL, string.ascii_lowercase),
        **_run(FIRST_SECOND_SCRIPT_DIGIT, string.digits),
        **SIGNS,
    }
)

# Mathematical italic, bold and the like, and the broken font's delimiters:
# a page with neither is no page of mathematics, and its Indic or Ethiopic
# letters are letters. A line of script letters under a stretched
# parenthesis can sit on a page with no italic letter on it.
MATH_ALPHANUMERICS = range(0x1D400, 0x1D800)
DELIMITERS = frozenset(key for key, sign in SIGNS.items() if sign in "()[]{}")


def restore(text: str) -> str:
    """The text with the broken font's letters read as what they show."""
    if not any(_marks_mathematics(character) for character in text):
        return text
    return text.translate(GLYPHS)


def _marks_mathematics(character: str) -> bool:
    return ord(character) in MATH_ALPHANUMERICS or character in DELIMITERS
