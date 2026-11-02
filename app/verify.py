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
from app import config, generate
from app.chunk import Chunk

FENCE_RE = re.compile(r"^```[^\n]*\n(.*?)^```", re.MULTILINE | re.DOTALL)
# A watermark digest has letters and digits; a 32-bit number written in
# binary is all digits and is the book's own text.
DIGEST_RE = re.compile(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{32}\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
WORD_RE = re.compile(r"\w+")


@dataclass
class Report:
    """What the checks found in one chunk's note."""

    chunk: Chunk
    path: Path
    written: bool = False
    code_lines: int = 0
    code_found: int = 0
    code_exact: int = 0
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
    """
    wanted = [line.rstrip() for line in _code_lines(source) if line.strip()]
    have = [line.rstrip() for line in _code_lines(note)]
    squeezed = {_squeeze(line) for line in have}
    exact = set(have)
    report.code_lines = len(wanted)
    report.code_found = sum(_squeeze(line) in squeezed for line in wanted)
    report.code_exact = sum(line in exact for line in wanted)
    if wanted and report.code_found < config.VERIFY_MIN_CODE_SHARE * len(wanted):
        report.problems.append(
            f"listings: {report.code_found} of {len(wanted)} source lines in the note"
        )


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
        flagged = sum(bool(report.problems) for report in written)
        name = "unsorted" if chapter is None else f"chapter {chapter}"
        lines.append(
            f"{name}: {len(written)}/{len(group)} notes{listing}, {flagged} flagged"
        )
    for report in reports:
        for problem in report.problems:
            lines.append(f"  {report.chunk.section} {report.chunk.title}: {problem}")
    return lines
