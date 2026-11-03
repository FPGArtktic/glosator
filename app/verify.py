# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Check a book's notes against the text each was written from.

No model is involved. These are the checks a reader would otherwise make by
hand after every chapter, before the run goes on: is there a note for every
chunk, did the listings reach it as printed, did the publisher's watermark
or a mail address the source does not have get in, and is any note so short
that it cannot cover its pages.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from app import chunk as chunk_module
from app import config
from app.chunk import Chunk

FENCE_RE = re.compile(r"^```[^\n]*\n(.*?)^```", re.MULTILINE | re.DOTALL)
# A watermark digest has letters and digits; a 32-bit number written in
# binary is all digits and is the book's own text.
DIGEST_RE = re.compile(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{32}\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
WORD_RE = re.compile(r"\w+")
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
TABLE_RULE_RE = re.compile(r"^\|[\s:|-]+\|$")
# The model sets a cell's mathematics as LaTeX; the book prints it as text.
# A cell is compared without its dollars and with these commands as the
# characters they stand for.
LATEX_SYMBOLS = {
    "\\infty": "∞",
    "\\neq": "≠",
    "\\ne": "≠",
    "\\leq": "≤",
    "\\le": "≤",
    "\\geq": "≥",
    "\\ge": "≥",
    "\\times": "\u00d7",
    "\\cdot": "·",
    "\\pm": "±",
    "\\oplus": "⊕",
    "\\ldots": "…",
    "\\dots": "…",
    "\\cap": "∩",
    "\\cup": "\u222a",
    "\\leftarrow": "←",
    "\\gets": "←",
    "\\Leftarrow": "⇐",
    "\\Rightarrow": "⇒",
    "\\leftrightarrow": "↔",
    "\\Leftrightarrow": "⇔",
    "\\approx": "≈",
    "\\equiv": "≡",
    "\\div": "÷",
    "\\neg": "¬",
    "\\lnot": "¬",
    "\\wedge": "∧",
    "\\land": "∧",
    "\\vee": "\u2228",
    "\\lor": "\u2228",
    "\\rightarrow": "→",
    "\\to": "→",
}
LATEX_SYMBOL_RE = re.compile(
    "(?:"
    + "|".join(re.escape(name) for name in sorted(LATEX_SYMBOLS, key=len, reverse=True))
    + r")(?![A-Za-z])"
)


@dataclass
class Report:
    """What the checks found in one chunk's note."""

    chunk: Chunk
    path: Path
    written: bool = False
    code_lines: int = 0
    code_found: int = 0
    code_exact: int = 0
    table_rows: int = 0
    table_found: int = 0
    problems: list[str] = field(default_factory=list)


def check(report: Report, note: str, source: str, *, listings: bool) -> Report:
    """Run the checks on one written note into its report."""
    report.written = True
    if DIGEST_RE.search(note):
        report.problems.append("a watermark digest is in the note")
    stray = set(EMAIL_RE.findall(note)) - set(EMAIL_RE.findall(source))
    if stray:
        report.problems.append(f"mail address not in the source: {sorted(stray)[0]}")
    if listings:
        _check_listings(report, note, source)
    _check_tables(report, note, source)
    note_words = len(WORD_RE.findall(note))
    source_words = len(WORD_RE.findall(source))
    if source_words and note_words < config.VERIFY_MIN_WORD_SHARE * source_words:
        report.problems.append(
            f"{note_words} words for {source_words} of source: too short to cover it"
        )
    return report


def _check_listings(report: Report, note: str, source: str) -> None:
    """Every line of the source's listings should be in the note's code.

    Found compares lines with their spacing squeezed; exact compares them as
    printed, indentation included. A listing the model rewrote loses lines
    from both, one it re-indented only from the second.

    The prompt sends an expression quoted in a sentence to the explanation,
    between backticks, and a table set as aligned text to a markdown table;
    a line found there counts as found, though never as exact.
    """
    wanted = [line.rstrip() for line in _code_lines(source) if line.strip()]
    have = [line.rstrip() for line in _code_lines(note)]
    squeezed = {_squeeze(line) for line in have}
    squeezed |= {_squeeze(span) for span in INLINE_CODE_RE.findall(note)}
    squeezed |= {
        _squeeze(_cells(row)) for row in note.splitlines() if row.startswith("|")
    }
    exact = set(have)
    report.code_lines = len(wanted)
    report.code_found = sum(_found(_squeeze(line), squeezed) for line in wanted)
    report.code_exact = sum(line in exact for line in wanted)
    if wanted and report.code_found < config.VERIFY_MIN_CODE_SHARE * len(wanted):
        report.problems.append(
            f"listings: {report.code_found} of {len(wanted)} source lines in the note"
        )


def _cells(row: str) -> str:
    """A table row's text without its rules and backticks."""
    return row.replace("|", " ").replace("`", "")


def _found(line: str, have: set[str]) -> bool:
    """A line of the source is in the note, or inside a longer line of it.

    The book quotes a program's lines in its prose ("lower = 0;") before or
    after printing the program, where the same line carries a comment.
    """
    if line in have:
        return True
    return len(line) >= config.VERIFY_MIN_QUOTED_CHARS and any(
        line in other for other in have
    )


def _check_tables(report: Report, note: str, source: str) -> None:
    """Every row of the source's tables should be a row of the note's."""
    wanted = _table_rows(source)
    have = _table_rows(note)
    report.table_rows = len(wanted)
    report.table_found = sum(_row_found(row, have) for row in wanted)
    if wanted and report.table_found < config.VERIFY_MIN_TABLE_SHARE * len(wanted):
        report.problems.append(
            f"tables: {report.table_found} of {len(wanted)} source rows in the note"
        )


def _row_found(row: str, have: Sequence[str]) -> bool:
    """A source row is a row of the note, or part of a longer one.

    A cell the book spans over several rows is printed in the first of
    them only, and the rows under it hold the rest of their cells; the
    model repeats the spanned cell in each. Such a partial row, one with
    empty cells or a single one, is found when its cells stand in that
    order in a note row with more of them. A full row must match whole:
    a truth table's "0|1" is in order in every longer row of digits.
    """
    if row in have:
        return True
    every = row.split("|")
    cells = [cell for cell in every if cell]
    if len(cells) == len(every) and len(cells) > 1:
        return False
    return any(_in_order(cells, other.split("|")) for other in have)


def _in_order(cells: list[str], other: list[str]) -> bool:
    """The cells are among the other row's, in order, and are fewer."""
    filled = [cell for cell in other if cell]
    if len(cells) >= len(filled):
        return False
    remaining = iter(filled)
    return all(cell in remaining for cell in cells)


def _table_rows(text: str) -> list[str]:
    """Rows of the markdown tables in the text, cells squeezed, rules left out."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or TABLE_RULE_RE.match(line):
            continue
        cells = [_cell(cell) for cell in line.strip("|").split("|")]
        if any(cells):
            rows.append("|".join(cells))
    return rows


def _cell(cell: str) -> str:
    """A table cell as the book would print it, spacing squeezed."""
    # The model sets code in a cell between backticks; the book does not.
    cell = cell.replace("`", "").replace("$", "")
    cell = LATEX_SYMBOL_RE.sub(lambda match: LATEX_SYMBOLS[match.group()], cell)
    return _squeeze(cell)


def _code_lines(text: str) -> list[str]:
    return [line for block in FENCE_RE.findall(text) for line in block.split("\n")]


def _squeeze(line: str) -> str:
    return " ".join(line.split())


def run(
    book_slug: str,
    out_dir: Path | str | None,
    *,
    listings: bool,
    chapter: int | None = None,
) -> list[Report]:
    """Reports for every chunk of the plan, or of one chapter of it."""
    # generate checks every answer with check(); importing it at the top
    # would make the two modules import each other.
    from app import generate

    chunks = chunk_module.load_plan(book_slug)
    titles = chunk_module.chapter_titles(chunks)
    reports = []
    for item in chunks:
        if chapter is not None and item.chapter != chapter:
            continue
        path = generate.note_path(item, titles.get(item.chapter or 0, ""), out_dir)
        report = Report(item, path)
        if path.exists():
            check(
                report,
                _body(path.read_text(encoding="utf-8")),
                item.text_path.read_text(encoding="utf-8"),
                listings=listings,
            )
        reports.append(report)
    return reports


def _body(note: str) -> str:
    """The note without its frontmatter, whose tags and title are not content."""
    if note.startswith("---\n"):
        end = note.find("\n---\n", 4)
        if end != -1:
            return note[end + 5 :]
    return note


def summary(reports: Sequence[Report]) -> list[str]:
    """One line per chapter, then one per note with a problem."""
    lines = []
    by_chapter: dict[int | None, list[Report]] = {}
    for report in reports:
        by_chapter.setdefault(report.chunk.chapter, []).append(report)
    for chapter, group in by_chapter.items():
        written = [report for report in group if report.written]
        code = sum(report.code_lines for report in written)
        found = sum(report.code_found for report in written)
        exact = sum(report.code_exact for report in written)
        listing = f", listings {found}/{code} lines ({exact} exact)" if code else ""
        rows = sum(report.table_rows for report in written)
        if rows:
            found_rows = sum(report.table_found for report in written)
            listing += f", tables {found_rows}/{rows} rows"
        flagged = sum(bool(report.problems) for report in written)
        name = "unsorted" if chapter is None else f"chapter {chapter}"
        lines.append(
            f"{name}: {len(written)}/{len(group)} notes{listing}, {flagged} flagged"
        )
    for report in reports:
        for problem in report.problems:
            lines.append(f"  {report.chunk.section} {report.chunk.title}: {problem}")
    return lines
