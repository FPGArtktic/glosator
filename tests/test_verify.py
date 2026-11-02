# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Checking notes against their source, without a model."""

from __future__ import annotations

from pathlib import Path

from app import verify
from app.chunk import Chunk

SOURCE = """## 2.1 Counting

Text about counting.

```
int count(const char *s)
{
    int n = 0;
    while (*s++)
        n++;
    return n;
}
```
"""


def report() -> verify.Report:
    item = Chunk(1, 2, "2.1", "Counting", 10, 11, Path("/w/c.md"))
    return verify.Report(item, Path("/out/note.md"))


def note(code: str, words: int = 200) -> str:
    return "## W skrócie\n\n" + "słowo " * words + f"\n\n## Kod\n\n```c\n{code}\n```\n"


def test_a_listing_copied_as_printed_passes() -> None:
    code = SOURCE.split("```\n")[1]
    checked = verify.check(report(), note(code), SOURCE, listings=True)
    assert checked.problems == []
    assert (checked.code_found, checked.code_exact, checked.code_lines) == (7, 7, 7)


def test_a_reindented_listing_is_found_but_not_exact() -> None:
    code = SOURCE.split("```\n")[1].replace("    ", "  ")
    checked = verify.check(report(), note(code), SOURCE, listings=True)
    assert checked.problems == []
    assert (checked.code_found, checked.code_exact) == (7, 3)


def test_a_missing_listing_is_a_problem() -> None:
    checked = verify.check(report(), note("Brak w tej sekcji."), SOURCE, listings=True)
    assert checked.problems == ["listings: 0 of 7 source lines in the note"]


def test_listings_are_not_checked_for_other_books() -> None:
    checked = verify.check(report(), note(""), SOURCE, listings=False)
    assert checked.problems == []
    assert checked.code_lines == 0


def test_a_watermark_and_a_strange_address_are_problems() -> None:
    code = SOURCE.split("```\n")[1]
    text = note(code) + "\n31d7100cb5017e6f233b4c258b20e87e reader@example.org\n"
    problems = verify.check(report(), text, SOURCE, listings=True).problems
    assert problems == [
        "a watermark digest is in the note",
        "mail address not in the source: reader@example.org",
    ]


def test_a_binary_number_is_not_a_watermark() -> None:
    code = SOURCE.split("```\n")[1]
    text = note(code) + "\n" + "01" * 16 + "\n"
    assert verify.check(report(), text, SOURCE, listings=True).problems == []


def test_a_note_far_shorter_than_its_source_is_a_problem() -> None:
    source = "word " * 3000
    problems = verify.check(report(), note("", words=50), source, listings=False)
    assert problems.problems[0].endswith("too short to cover it")


def test_summary_counts_notes_per_chapter() -> None:
    written = verify.check(report(), note("Brak."), SOURCE, listings=True)
    missing = report()
    lines = verify.summary([written, missing])
    assert lines[0] == "chapter 2: 1/2 notes, listings 0/7 lines (0 exact), 1 flagged"
    assert lines[1].startswith("  2.1 Counting: listings")
