# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""The language a book's notes are written in.

Notes follow their book: an English book gets English notes with a Polish
glossary, a Polish one Polish notes with an English glossary. The model
always answers under the contract's English headings, which the code parses;
the headings written into a note are the note's own language.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from app import config

POLISH_LETTERS = frozenset("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")


@dataclass(frozen=True)
class Language:
    code: str
    # How the prompts name it: "Write the note in Polish".
    name: str
    # The glossary rules for this direction, a file under app/prompts.
    glossary_prompt: str
    # Fixed text the index writes into the chapter maps and the glossary.
    glossary_title: str
    reading_order: str
    pages: str
    # Contract heading to the heading written into a note; absent ones stay.
    headings: dict[str, str] = field(default_factory=dict)

    def heading(self, name: str) -> str:
        return self.headings.get(name, name)


ENGLISH = Language(
    code="en",
    name="English",
    glossary_prompt="glossary-en.md",
    glossary_title="Glossary",
    reading_order="Notes in reading order:",
    pages="pages",
)
POLISH = Language(
    code="pl",
    name="Polish",
    glossary_prompt="glossary-pl.md",
    glossary_title="Słowniczek",
    reading_order="Notatki w kolejności czytania:",
    pages="strony",
    headings={
        "In short": "W skrócie",
        "Explanation": "Wyjaśnienie",
        "Code": "Kod",
        "Formulas": "Wzory",
        "Figures": "Rysunki",
        "Glossary": "Słowniczek",
        "Pitfalls": "Pułapki",
        "Exercises": "Ćwiczenia",
    },
)
LANGUAGES = {language.code: language for language in (ENGLISH, POLISH)}


def contract_name(heading: str) -> str:
    """The contract's name for a heading read back from a note, any language."""
    for language in LANGUAGES.values():
        for name, written in language.headings.items():
            if written == heading:
                return name
    return heading


def detect(text: str) -> Language:
    """Polish when enough of the letters are Polish ones, else English."""
    letters = [character for character in text if character.isalpha()]
    if not letters:
        return ENGLISH
    polish = sum(character in POLISH_LETTERS for character in letters)
    if polish / len(letters) >= config.POLISH_LETTER_MIN_SHARE:
        return POLISH
    return ENGLISH


def of_book(setting: str | None, texts: Iterable[str]) -> Language:
    """The language set for a book, or the one its text is in."""
    if setting:
        return LANGUAGES[setting]
    sample: list[str] = []
    size = 0
    for text in texts:
        sample.append(text)
        size += len(text)
        if size >= config.LANGUAGE_SAMPLE_CHARS:
            break
    return detect("".join(sample)[: config.LANGUAGE_SAMPLE_CHARS])
