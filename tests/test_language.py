# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Which language a book's notes are written in."""

from __future__ import annotations

from app import language
from app.language import ENGLISH, POLISH

POLISH_PROSE = (
    "Wtórnik emiterowy ma dużą impedancję wejściową i małą wyjściową, więc "
    "dobrze nadaje się do separowania źródła sygnału od obciążenia."
)
ENGLISH_PROSE = (
    "An emitter follower has a high input impedance and a low output "
    "impedance, so it isolates a signal source from its load."
)


def test_detect_tells_polish_from_english() -> None:
    assert language.detect(POLISH_PROSE) is POLISH
    assert language.detect(ENGLISH_PROSE) is ENGLISH


def test_detect_keeps_an_english_book_that_quotes_a_polish_name() -> None:
    assert language.detect(ENGLISH_PROSE * 5 + " Łukasiewicz notation.") is ENGLISH


def test_detect_of_no_text_is_english() -> None:
    assert language.detect("") is ENGLISH
    assert language.detect("1234 $$ \n") is ENGLISH


def test_a_setting_wins_over_the_text() -> None:
    assert language.of_book("en", [POLISH_PROSE]) is ENGLISH
    assert language.of_book("pl", [ENGLISH_PROSE]) is POLISH


def test_no_setting_follows_the_text() -> None:
    assert language.of_book(None, [POLISH_PROSE]) is POLISH
    assert language.of_book(None, [ENGLISH_PROSE]) is ENGLISH


def test_of_book_reads_no_further_than_its_sample(monkeypatch) -> None:
    monkeypatch.setattr(language.config, "LANGUAGE_SAMPLE_CHARS", 50)
    read: list[int] = []

    def texts():
        for number in range(100):
            read.append(number)
            yield POLISH_PROSE

    assert language.of_book(None, texts()) is POLISH
    assert len(read) == 1


def test_contract_name_reads_a_heading_back_in_either_language() -> None:
    assert language.contract_name("Słowniczek") == "Glossary"
    assert language.contract_name("Glossary") == "Glossary"
    assert language.contract_name("Ćwiczenia") == "Exercises"


def test_every_polish_heading_names_a_contract_section() -> None:
    from app import generate

    assert set(POLISH.headings) == set(generate.SECTION_ORDER)
