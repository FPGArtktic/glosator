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


def test_a_checksum_the_source_prints_is_not_a_watermark() -> None:
    line = 'CHKSUM = "file://LICENSE;md5=0a1b2c3d4e5f60718293a4b5c6d7e8f9"'
    source = f"A recipe names its licence:\n\n```\n{line}\n```\n"
    text = note(line)
    assert verify.check(report(), text, source, listings=True).problems == []


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


def test_a_line_quoted_without_its_comment_is_found() -> None:
    source = "```\nint n = 0;\n```\n"
    code = "int n = 0;  /* counter */"
    checked = verify.check(report(), note(code), source, listings=True)
    assert (checked.code_found, checked.code_exact) == (1, 0)


TABLE = (
    "| Operators | Associativity |\n|---|---|\n"
    "| () [] | left to right |\n| ! ~ | right to left |\n"
)


def test_a_table_copied_whole_passes_and_a_summarised_one_is_a_problem() -> None:
    copied = note("") + (
        "\n|Operators|Associativity|\n|:-|:-|\n"
        "|() []|left to right|\n|! ~|right to left|\n"
    )
    checked = verify.check(report(), copied, TABLE, listings=False)
    assert checked.problems == []
    assert (checked.table_found, checked.table_rows) == (3, 3)
    told = verify.check(
        report(), note("") + "\nThe table lists two rows.", TABLE, listings=False
    )
    assert told.problems == ["tables: 0 of 3 source rows in the note"]


def test_expressions_quoted_in_text_and_tables_count_as_found() -> None:
    source = "```\nisdigit(c)\n```\n\n```\n\\a bell    \\\\ backslash\n```\n"
    text = (
        note("") + "\nUse `isdigit(c)` here.\n\n| `\\a` | bell | `\\\\` | backslash |\n"
    )
    checked = verify.check(report(), text, source, listings=True)
    assert (checked.code_found, checked.code_exact, checked.code_lines) == (2, 0, 2)
    assert checked.problems == []


def test_a_table_row_matches_with_its_code_in_backticks() -> None:
    source = "| char *strcpy(s,ct) | copies ct to s |\n|---|---|\n"
    text = note("") + "\n| `char *strcpy(s,ct)` | copies `ct` to `s` |\n|---|---|\n"
    checked = verify.check(report(), text, source, listings=False)
    assert (checked.table_found, checked.table_rows) == (1, 1)


def test_a_table_row_matches_with_its_mathematics_as_latex() -> None:
    source = (
        "| plus infinity | 0 | ∞ |\n|---|---|---|\n| range | 10^{-38} | ≠ 0 |\n"
        "| 3 | OP A, B, C | A ← B OP C |\n"
    )
    text = note("") + (
        "\n| plus infinity | 0 | $\\infty$ |\n|---|---|---|\n"
        "| range | $10^{-38}$ | $\\neq 0$ |\n"
        "| 3 | OP A, B, C | $A \\leftarrow B$ OP C |\n"
    )
    checked = verify.check(report(), text, source, listings=False)
    assert (checked.table_found, checked.table_rows) == (3, 3)


def test_a_ruling_read_into_a_cell_does_not_hide_the_row() -> None:
    source = "| Pin | Mode |\n|---|---|\n| 0 | &#124;Serial flash |\n"
    text = note("") + "\n| Pin | Mode |\n|---|---|\n| 0 | Serial flash |\n"
    checked = verify.check(report(), text, source, listings=False)
    assert (checked.table_found, checked.table_rows) == (2, 2)


def test_a_row_under_a_spanned_cell_matches_the_row_that_repeats_it() -> None:
    source = (
        "| Space | Request | Purpose |\n|---|---|---|\n"
        "| Memory | read | moves data |\n| write |\n"
        "| 0 | 1 | 1 |\n"
    )
    text = note("") + (
        "\n| Space | Request | Purpose |\n|---|---|---|\n"
        "| Memory | read | moves data |\n| Memory | write | moves data |\n"
        "| 0 | 1 | 1 | 0 |\n"
    )
    checked = verify.check(report(), text, source, listings=False)
    # The truth-table row is as long as the note's and must match whole.
    assert (checked.table_found, checked.table_rows) == (3, 4)
